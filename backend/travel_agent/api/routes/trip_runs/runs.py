from __future__ import annotations
import logging
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException, Query
from travel_agent.bootstrap.registry import get_components
from travel_agent.runtime.run_lifecycle import available_run_actions
from travel_agent.runtime.local_identity import LOCAL_USER_ID
from travel_agent.api.schemas.runs import (
    TripRunCreateRequest,
    TripRunDetailResponse,
    TripRunListResponse,
    TripRunResponse,
)

from travel_agent.api.run_authorization import _get_authorized_run
from travel_agent.api.presenters.runs import (
    _run_response,
    _state_response,
    _execution_response,
    _event_responses,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/trip-runs", tags=["trip-runs"])


@router.post("", response_model=TripRunResponse)
async def create_trip_run(request: TripRunCreateRequest) -> TripRunResponse:
    if request.route_decision.route.value != "trip_planning":
        raise HTTPException(
            status_code=422, detail="只有已确认的旅行规划可以创建规划 TripRun"
        )
    components = get_components()
    run = await components.trip_run_store.create_run(
        session_id=request.session_id,
        user_id=LOCAL_USER_ID,
        mode="deep",
        request_message_id=request.request_message_id,
        assistant_message_id=request.assistant_message_id,
        parent_run_id=request.parent_run_id,
        controlled_trip_identity=request.controlled_trip_identity.model_dump(
            mode="json"
        ),
        route_decision=request.route_decision.model_dump(mode="json"),
    )
    return _run_response(run)


@router.get("", response_model=TripRunListResponse)
async def list_trip_runs(
    session_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    mode: Optional[Literal["deep", "fast"]] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> TripRunListResponse:
    components = get_components()
    try:
        runs = await components.trip_run_store.list_runs(
            user_id=LOCAL_USER_ID,
            session_id=session_id,
            status=status,
            mode=mode,
            limit=limit,
        )
        total = await components.trip_run_store.count_runs(
            user_id=LOCAL_USER_ID,
            session_id=session_id,
            status=status,
            mode=mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    titles = await components.trip_run_store.list_run_titles(
        [run.session_id for run in runs]
    )
    return TripRunListResponse(
        runs=[_run_response(run, title=titles.get(run.session_id)) for run in runs],
        total=total,
    )


@router.get("/{run_id}", response_model=TripRunDetailResponse)
async def read_trip_run(
    run_id: str,
    event_limit: int = Query(default=50, ge=0, le=200),
    session_id: Optional[str] = Query(default=None),
):
    components = get_components()
    await _get_authorized_run(run_id, session_id=session_id)
    detail = await components.trip_run_store.get_detail(run_id, event_limit=event_limit)
    if detail is None:
        raise HTTPException(status_code=404, detail="TripRun 不存在")
    execution = await components.run_execution_store.get(run_id)
    return TripRunDetailResponse(
        run=_run_response(detail.run),
        controlled_trip_identity=detail.run.controlled_trip_identity,
        state=_state_response(detail.state),
        execution=_execution_response(execution),
        available_actions=available_run_actions(detail.run, execution),
        events=_event_responses(detail.events),
    )
