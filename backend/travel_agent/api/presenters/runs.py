from __future__ import annotations
from typing import Any, Dict, Mapping, Optional
from travel_agent.runtime.run_contracts import TripRunStatus
from travel_agent.api.schemas.tools import ToolAuditRecordResponse
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
    """Inspect-surface run projection: codes/nodes yes, raw error prose never."""
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
    """Project the awaiting-input decision, or ``None`` when nobody can act on it.

    The durable column is a JSONB blob, but it has one live producer: the plan
    approval gate.  A shape no client can restore is not republished — a returning
    browser would only be able to render it as an unactionable waiting state.
    ``read_only`` / ``terminal_status`` are carried through because they are how a
    client tells "still waiting on you" from "this decision was cancelled".
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
    """Authorized inspect projection of run state (audit-safe, no dual mode)."""
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
    """Project durable events for product lifecycle + audit-safe inspect.

    Lifecycle boundaries stay product-shaped; other event types are included
    only after ``audit_safe_value`` strips raw I/O keys (inspect surface).
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


def _tool_audit_response(record) -> ToolAuditRecordResponse:
    return ToolAuditRecordResponse(
        audit_id=record.audit_id,
        run_id=record.run_id,
        tool_name=record.tool_name,
        server_name=record.server_name,
        source_type=record.source_type,
        category=record.category,
        permission_class=record.permission_class,
        operation_sensitivity=record.operation_sensitivity,
        status=record.status,
        gateway_decision=record.gateway_decision,
        args_digest=record.args_digest,
        result_digest=record.result_digest,
        untrusted_content=record.untrusted_content,
        quarantined=record.quarantined,
        fallback_from=record.fallback_from,
        fallback_to=record.fallback_to,
        degradation_reason=None,
        error=None,
        evidence_allowed=record.evidence_allowed,
        metadata=audit_safe_value(record.metadata),
        created_at=record.created_at,
    )
