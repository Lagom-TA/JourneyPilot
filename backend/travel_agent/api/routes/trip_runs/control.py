from __future__ import annotations
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from travel_agent.bootstrap.registry import get_components
from travel_agent.api.schemas.commands import (
    TripRunCommandResponse,
    TripRunControlRequest,
    TripRunControlResponse,
    TripRunSupplementRequest,
    TripRunSupplementResponse,
)
from travel_agent.runtime.cancellation import run_control_registry

from travel_agent.api.run_authorization import _get_authorized_run
from travel_agent.api.run_errors import raise_run_use_case_error
from travel_agent.planning.run_control import cancel_run
from travel_agent.planning.requirements.supplements import queue_supplement
from travel_agent.planning.run_errors import (
    RunNotFound,
    RunNotCancellable,
    LockedIdentitySupplement,
    RunNotAcceptingSupplement,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/trip-runs", tags=["trip-runs"])


@router.post("/{run_id}/supplements", response_model=TripRunSupplementResponse)
async def add_trip_run_supplement(
    run_id: str, request: TripRunSupplementRequest
) -> TripRunSupplementResponse:
    """在下一个可协作节点边界追加要求。

    要求先写入 `trip_run_commands` 再通知执行器，是否接受不取决于请求命中哪个进程。
    通知丢失或进程切换后，执行器下一次轮询仍能读到该命令。

    该接口不能修改受控旅行身份；身份变更必须新建 TripRun，避免简报、行程与地图
    出现不一致。
    """
    components = get_components()
    detail = await components.trip_run_store.get_detail(run_id, event_limit=0)
    if detail is None:
        raise HTTPException(status_code=404, detail="TripRun 不存在")
    if request.session_id and detail.run.session_id != request.session_id:
        raise HTTPException(status_code=403, detail="无权修改该 TripRun")
    try:
        outcome = await queue_supplement(
            run_id,
            run=detail.run,
            category=request.category,
            content=request.content,
            trip_run_store=components.trip_run_store,
            command_store=components.run_command_store,
            notify=run_control_registry.notify,
        )
    except (LockedIdentitySupplement, RunNotAcceptingSupplement) as error:
        raise_run_use_case_error(error)
    command = outcome.command
    return TripRunSupplementResponse(
        run_id=run_id,
        command_id=command.command_id,
        accepted=True,
        status=command.status.value,
        category=request.category,
        message=outcome.message,
        impact_scope=outcome.impact_scope,
    )


@router.post("/{run_id}/control", response_model=TripRunControlResponse)
async def control_trip_run(
    run_id: str, request: TripRunControlRequest
) -> TripRunControlResponse:
    """取消一次运行：先写入持久命令，再更新状态，最后通知执行器。

    顺序有依赖：命令先落库，保证「已接受」在进程重启后仍然成立；随后进行状态转换，
    `cancel_requested` 写入 `trip_runs` 后，交付边界的 `FOR UPDATE` 无法再提交
    completion。进程内通知是最后一步，仅用于减少一个轮询周期的等待，未命中不影响结果。
    """

    components = get_components()
    detail = await components.trip_run_store.get_detail(run_id, event_limit=0)
    if detail is None:
        raise HTTPException(status_code=404, detail="TripRun 不存在")
    if request.session_id and detail.run.session_id != request.session_id:
        raise HTTPException(status_code=403, detail="无权控制该 TripRun")
    try:
        outcome = await cancel_run(
            run_id,
            initial_run=detail.run,
            trip_run_store=components.trip_run_store,
            execution_store=components.run_execution_store,
            command_store=components.run_command_store,
            notify=run_control_registry.notify,
        )
    except (RunNotFound, RunNotCancellable) as error:
        raise_run_use_case_error(error)
    return TripRunControlResponse(
        run_id=run_id,
        action=request.action,
        command_id=outcome.command.command_id,
        accepted=True,
        status=outcome.command.status.value,
        run_status=outcome.run.status.value,
        message=outcome.message,
    )


@router.get("/{run_id}/commands/{command_id}", response_model=TripRunCommandResponse)
async def read_trip_run_command(
    run_id: str,
    command_id: str,
    session_id: Optional[str] = Query(default=None),
) -> TripRunCommandResponse:
    """返回一条控制命令的结论；断线后查询即可，无需重复发送取消。"""

    components = get_components()
    run = await _get_authorized_run(run_id, session_id=session_id)
    command = await components.run_command_store.get(run_id, command_id)
    if command is None:
        raise HTTPException(status_code=404, detail="控制命令不存在")
    return TripRunCommandResponse(
        command_id=command.command_id,
        run_id=command.run_id,
        command_type=command.command_type.value,
        status=command.status.value,
        run_status=run.status.value,
        error_code=command.error_code,
        result=command.result,
        created_at=command.created_at,
        updated_at=command.updated_at,
        consumed_at=command.consumed_at,
    )
