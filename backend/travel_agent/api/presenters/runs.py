from __future__ import annotations
from typing import Any, Dict, Mapping, Optional
from travel_agent.runtime.run_contracts import TripRunStatus
from travel_agent.api.schemas.runs import (
    TripRunEventResponse,
    TripRunExecutionResponse,
    TripRunResponse,
    TripRunStateResponse,
)
from travel_agent.api.audit_projection import audit_safe_value
from travel_agent.api.sse_projection import public_plan_gate_payload
from travel_agent.planning.delivery.public.bundle import public_event_manifest


def _run_response(
    run,
    *,
    title: Optional[str] = None,
) -> TripRunResponse:
    """检视界面的 run 投影：保留原因码与节点，不下发原始错误文本。"""
    return TripRunResponse(
        run_id=run.run_id,
        session_id=run.session_id,
        mode=run.mode.value,
        status=run.status.value,
        title=title,
        request_message_id=run.request_message_id,
        assistant_message_id=run.assistant_message_id,
        parent_run_id=run.parent_run_id,
        current_node=run.current_node,
        resume_policy=run.resume_policy.value,
        last_error_code=run.last_error_code,
        last_error_message=None,
        attempt=run.attempt,
        created_at=run.created_at,
        updated_at=run.updated_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        cancelled_at=run.cancelled_at,
    )


def _public_pending_user_choice(choice: Any) -> Optional[Dict[str, Any]]:
    """投影待输入决策；无法恢复的决策返回 None。

    持久列是 JSONB，当前只有计划审批门一个写入方。客户端无法恢复的决策不再下发，
    避免恢复会话时只显示无法操作的等待状态。``read_only`` / ``terminal_status``
    保留，用于区分仍在等待与决策已取消。
    """

    if not isinstance(choice, Mapping):
        return None
    if str(choice.get("type") or "") != "approval_gate":
        return None
    projected: Dict[str, Any] = {
        "type": "approval_gate",
        "gate": choice.get("gate"),
        "payload": public_plan_gate_payload(choice.get("payload")),
    }
    if choice.get("read_only"):
        projected["read_only"] = True
        projected["terminal_status"] = choice.get("terminal_status")
    return projected


def _state_response(state) -> TripRunStateResponse:
    """run 状态的检视投影（经脱敏，无双重模式）。"""
    return TripRunStateResponse(
        run_id=state.run_id,
        status=state.status.value,
        current_node=state.current_node,
        completed_nodes=list(state.completed_nodes or []),
        latest_state_summary=audit_safe_value(state.latest_state_summary or {}),
        pending_user_choice=_public_pending_user_choice(state.pending_user_choice),
        trace_event_count=state.trace_event_count,
        pending_monitor_trigger_count=state.pending_monitor_trigger_count,
        last_error=audit_safe_value(state.last_error) if state.last_error else None,
        updated_at=state.updated_at,
    )


def _execution_response(execution) -> Optional[TripRunExecutionResponse]:
    """执行归属的公开投影。`executor_id` 与 `lease_token` 留在服务端：

    前者是主机名加进程标识，后者是抢占租约的凭据，两个都不是客户端需要的东西。
    """

    if execution is None:
        return None
    return TripRunExecutionResponse(
        status=execution.recovery_status.value,
        last_heartbeat_at=execution.heartbeat_at,
        lease_expires_at=execution.lease_expires_at,
        last_safe_checkpoint_id=execution.last_safe_checkpoint_id,
        recovery_reason=execution.recovery_reason,
    )


def _event_response(event) -> Optional[TripRunEventResponse]:
    """投影持久事件：生命周期事件按产品形态下发，其他事件经脱敏后下发。

    ``audit_safe_value`` 会剔除其他事件载荷中的原始 I/O 字段。
    """
    if event.event_type in {"delivery.ready", "bundle.current_changed"}:
        payload = {
            "bundle_id": event.payload.get("bundle_id"),
            "manifest": public_event_manifest(event.payload.get("manifest")),
        }
    elif event.event_type == "run.terminal":
        payload = {
            "status": event.payload.get("status"),
            "bundle_id": event.payload.get("bundle_id"),
        }
    elif event.event_type in {"run.completed", "run.cancelled", "run.interrupted"}:
        payload = {"status": event.event_type.removeprefix("run.")}
    elif event.event_type in {"run.awaiting_input", "run.gate_raised"}:
        payload = {"status": TripRunStatus.AWAITING_INPUT.value}
    elif event.event_type == "run.guard_blocked":
        payload = {
            "status": TripRunStatus.FAILED.value,
            "message": "这次请求未通过安全策略检查，已被拒绝执行。",
        }
    elif event.event_type == "run.failed":
        payload = {
            "status": TripRunStatus.FAILED.value,
            "message": "旅行方案暂时无法生成，请稍后重试。",
        }
        reason = event.payload.get("reason_code")
        if reason:
            payload["reason_code"] = reason
    elif event.event_type in {"run.created", "run.started", "run.control_requested"}:
        payload = {}
    else:
        scrubbed = audit_safe_value(event.payload or {})
        payload = scrubbed if isinstance(scrubbed, dict) else {}
    return TripRunEventResponse(
        event_id=event.event_id,
        run_id=event.run_id,
        sequence=event.sequence,
        event_type=event.event_type,
        payload=payload,
        created_at=event.created_at,
    )


def _event_responses(events) -> list[TripRunEventResponse]:
    return [
        response for event in events if (response := _event_response(event)) is not None
    ]
