"""TripRun 与执行租约的数据契约。"""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel
from pydantic import Field
from travel_agent.runtime.local_identity import LOCAL_USER_ID
from travel_agent.runtime.time import utc_now_iso
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
import uuid


def generate_trip_run_id() -> str:
    return f"trip_{uuid.uuid4().hex[:16]}"


class TripRunStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


class TripRunMode(str, Enum):
    DEEP = "deep"
    FAST = "fast"


class TripRunResumePolicy(str, Enum):
    CLARIFY_ONLY = "clarify_only"
    RESTART_FROM_LATEST_INPUT = "restart_from_latest_input"
    CHECKPOINT = "checkpoint"


class RunRecoveryStatus(str, Enum):
    """执行归属的生命周期。与 TripRunStatus 正交：前者说「谁在跑」，后者说「跑到哪」。"""

    IDLE = "idle"
    CLAIMED = "claimed"
    RUNNING = "running"

    SHUTDOWN_REQUESTED = "shutdown_requested"
    RESUME_AVAILABLE = "resume_available"
    NON_RESUMABLE = "non_resumable"
    RELEASED = "released"

    RECOVERY_CONTRACT_FAILURE = "recovery_contract_failure"


class RunExecution(BaseModel):
    """一个 TripRun 的执行租约与恢复判定。租约时钟以数据库 NOW() 为准。"""

    run_id: str
    executor_id: Optional[str] = None
    lease_token: Optional[str] = None
    lease_acquired_at: Optional[str] = None
    lease_expires_at: Optional[str] = None
    heartbeat_at: Optional[str] = None
    process_started_at: Optional[str] = None
    last_safe_checkpoint_id: Optional[str] = None
    recovery_status: RunRecoveryStatus = RunRecoveryStatus.IDLE
    recovery_reason: Optional[str] = None
    updated_at: str = Field(default_factory=utc_now_iso)


def coerce_status(value: str | TripRunStatus) -> TripRunStatus:
    return value if isinstance(value, TripRunStatus) else TripRunStatus(str(value))


def coerce_mode(value: str | TripRunMode) -> TripRunMode:
    return value if isinstance(value, TripRunMode) else TripRunMode(str(value))


def coerce_resume_policy(value: str | TripRunResumePolicy) -> TripRunResumePolicy:
    return (
        value
        if isinstance(value, TripRunResumePolicy)
        else TripRunResumePolicy(str(value))
    )


def coerce_recovery_status(value: str | RunRecoveryStatus) -> RunRecoveryStatus:
    return (
        value if isinstance(value, RunRecoveryStatus) else RunRecoveryStatus(str(value))
    )


class TripRun(BaseModel):
    run_id: str
    session_id: str = ""
    user_id: str = LOCAL_USER_ID
    mode: TripRunMode = TripRunMode.DEEP
    status: TripRunStatus = TripRunStatus.CREATED
    request_message_id: str = ""
    assistant_message_id: str = ""
    parent_run_id: Optional[str] = None
    current_node: Optional[str] = None
    resume_token_hash: Optional[str] = None
    resume_policy: TripRunResumePolicy = TripRunResumePolicy.CLARIFY_ONLY

    controlled_trip_identity: Optional[Dict[str, Any]] = None
    last_error_code: Optional[str] = None
    last_error_message: Optional[str] = None
    attempt: int = 1
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    cancelled_at: Optional[str] = None


class TripRunState(BaseModel):
    run_id: str
    status: TripRunStatus = TripRunStatus.CREATED
    current_node: Optional[str] = None
    completed_nodes: List[str] = Field(default_factory=list)
    latest_state_summary: Dict[str, Any] = Field(default_factory=dict)

    pending_user_choice: Optional[Dict[str, Any]] = None
    trace_event_count: int = 0
    pending_monitor_trigger_count: int = 0
    last_error: Optional[Dict[str, Any]] = None
    updated_at: str = Field(default_factory=utc_now_iso)


class TripRunEvent(BaseModel):
    event_id: Optional[int] = None
    run_id: str
    sequence: int
    event_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)


class TripRunDetail(BaseModel):
    run: TripRun
    state: TripRunState
    events: List[TripRunEvent] = Field(default_factory=list)
