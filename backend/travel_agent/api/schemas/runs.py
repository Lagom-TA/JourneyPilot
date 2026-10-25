from __future__ import annotations

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from pydantic import BaseModel
from pydantic import Field
from travel_agent.planning.requirements.identity_contracts import ControlledTripIdentity
from travel_agent.conversation.intake_contracts import RouteDecision


class TripRunCreateRequest(BaseModel):
    session_id: str = ""
    route_decision: RouteDecision
    controlled_trip_identity: ControlledTripIdentity
    request_message_id: str = ""
    assistant_message_id: str = ""
    parent_run_id: Optional[str] = None


class TripRunResponse(BaseModel):
    run_id: str
    session_id: str
    mode: str
    status: str
    title: Optional[str] = None
    request_message_id: str = ""
    assistant_message_id: str = ""
    parent_run_id: Optional[str] = None
    current_node: Optional[str] = None
    resume_policy: str = "clarify_only"
    last_error_code: Optional[str] = None
    last_error_message: Optional[str] = None
    attempt: int = 1
    created_at: str
    updated_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    cancelled_at: Optional[str] = None


class TripRunStateResponse(BaseModel):
    run_id: str
    status: str
    current_node: Optional[str] = None
    completed_nodes: List[str] = Field(default_factory=list)
    latest_state_summary: Dict[str, Any] = Field(default_factory=dict)
    pending_user_choice: Optional[Dict[str, Any]] = None
    trace_event_count: int = 0
    pending_monitor_trigger_count: int = 0
    last_error: Optional[Dict[str, Any]] = None
    updated_at: str


class TripRunEventResponse(BaseModel):
    event_id: Optional[int] = None
    run_id: str
    sequence: int
    event_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: str


class TripRunEventWindowResponse(BaseModel):
    run_id: str
    requested_after_sequence: int
    replay_floor_sequence: int
    latest_sequence: int
    next_after_sequence: int
    window_expired: bool
    run_status: str
    current_bundle_id: Optional[str] = None
    events: List[TripRunEventResponse] = Field(default_factory=list)


class TripRunExecutionResponse(BaseModel):
    """执行归属与恢复判定。`status` 与 TripRun 的业务状态是两件事。"""

    status: str
    last_heartbeat_at: Optional[str] = None
    lease_expires_at: Optional[str] = None
    last_safe_checkpoint_id: Optional[str] = None
    recovery_reason: Optional[str] = None


class TripRunDetailResponse(BaseModel):
    run: TripRunResponse
    controlled_trip_identity: Optional[ControlledTripIdentity] = None
    state: TripRunStateResponse
    execution: Optional[TripRunExecutionResponse] = None
    # 服务端说清这个 run 现在能做什么，客户端不从状态、resume_policy 与恢复判定里自己推。
    available_actions: List[str] = Field(default_factory=list)
    events: List[TripRunEventResponse] = Field(default_factory=list)


class TripRunListResponse(BaseModel):
    runs: List[TripRunResponse] = Field(default_factory=list)
    total: int = Field(
        default=0,
        description=(
            "Number of TripRuns matching the query filters (session_id/status/"
            "mode), ignoring `limit`. May exceed len(runs) when the page "
            "is truncated."
        ),
    )


class TripRunCompletionDiagnosticsResponse(BaseModel):
    """Developer/Eval-only, audit-safe completion diagnostic summary."""

    run_id: str
    status: str
    completion_audit: Dict[str, Any] = Field(default_factory=dict)
