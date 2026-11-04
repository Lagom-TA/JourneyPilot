"""TripRun 状态迁移规则与可用动作。"""

from __future__ import annotations

from travel_agent.runtime.run_contracts import RunRecoveryStatus, TripRun, RunExecution
from travel_agent.runtime.run_contracts import TripRunResumePolicy
from travel_agent.runtime.run_contracts import TripRunStatus
from travel_agent.runtime.run_contracts import coerce_status
from typing import Dict
from typing import List
from typing import Optional
from typing import Any


TERMINAL_TRIP_RUN_STATUSES: set[TripRunStatus] = {
    TripRunStatus.COMPLETED,
    TripRunStatus.FAILED,
    TripRunStatus.INTERRUPTED,
    TripRunStatus.CANCELLED,
}


def with_pending_choice_summary(
    summary: Any, *, pending: bool
) -> Dict[str, Any]:
    """返回修正过交互标记的追踪摘要副本。"""
    data = dict(summary) if isinstance(summary, dict) else {}
    data["pending_user_choice"] = bool(pending)
    return data


def mark_cancelled_pending_choice(value: Any) -> Optional[Dict[str, Any]]:
    """把当前决策保存为取消终态的只读审计快照。"""
    if not isinstance(value, dict) or not value:
        return None
    return {
        **value,
        "read_only": True,
        "terminal_status": TripRunStatus.CANCELLED.value,
    }


ALLOWED_STATUS_TRANSITIONS: Dict[TripRunStatus, set[TripRunStatus]] = {
    TripRunStatus.CREATED: {
        TripRunStatus.RUNNING,
        TripRunStatus.CANCELLED,
        TripRunStatus.FAILED,
    },
    TripRunStatus.RUNNING: {
        TripRunStatus.AWAITING_INPUT,
        TripRunStatus.COMPLETED,
        TripRunStatus.FAILED,
        TripRunStatus.INTERRUPTED,
        TripRunStatus.CANCEL_REQUESTED,
    },
    TripRunStatus.AWAITING_INPUT: {
        TripRunStatus.RUNNING,
        TripRunStatus.FAILED,
        TripRunStatus.CANCELLED,
    },
    TripRunStatus.FAILED: {TripRunStatus.RUNNING},
    TripRunStatus.INTERRUPTED: {TripRunStatus.RUNNING},
    TripRunStatus.CANCEL_REQUESTED: {TripRunStatus.CANCELLED},
    TripRunStatus.COMPLETED: set(),
    TripRunStatus.CANCELLED: set(),
}


def is_status_transition_allowed(
    current: str | TripRunStatus,
    target: str | TripRunStatus,
    *,
    allow_same: bool = True,
) -> bool:
    current_status = coerce_status(current)
    target_status = coerce_status(target)
    if allow_same and current_status == target_status:
        return True
    return target_status in ALLOWED_STATUS_TRANSITIONS[current_status]


def assert_status_transition_allowed(
    current: str | TripRunStatus,
    target: str | TripRunStatus,
    *,
    allow_same: bool = True,
) -> None:
    if not is_status_transition_allowed(current, target, allow_same=allow_same):
        raise ValueError(f"invalid TripRun status transition: {current} -> {target}")


def is_terminal_status(value: str | TripRunStatus) -> bool:
    return coerce_status(value) in TERMINAL_TRIP_RUN_STATUSES


_CANCELLABLE_STATUSES = {
    TripRunStatus.CREATED,
    TripRunStatus.RUNNING,
    TripRunStatus.AWAITING_INPUT,
    TripRunStatus.CANCEL_REQUESTED,
}


_RESUMABLE_STATUSES = {
    TripRunStatus.CREATED,
    TripRunStatus.AWAITING_INPUT,
    TripRunStatus.FAILED,
    TripRunStatus.INTERRUPTED,
}


def is_cancellable(status: TripRunStatus | str) -> bool:
    """这个状态还能不能被取消。路由的前置判断与 `available_run_actions`
    读取同一张表，避免界面显示的动作与实际允许的动作不一致。
    """

    return coerce_status(status) in _CANCELLABLE_STATUSES


def available_run_actions(
    run: "TripRun",
    execution: Optional["RunExecution"] = None,
) -> List[str]:
    """这个 Run 现在真正能做的动作。

    服务端统一给出，客户端不依据多个字段自行推导，避免界面动作与实际状态分叉。
    """

    actions: List[str] = []
    resumable = run.status in _RESUMABLE_STATUSES and (
        run.resume_policy == TripRunResumePolicy.CHECKPOINT
        or run.status == TripRunStatus.CREATED
    )
    if execution is not None and execution.recovery_status in {
        RunRecoveryStatus.NON_RESUMABLE,
        RunRecoveryStatus.RECOVERY_CONTRACT_FAILURE,
    }:
        resumable = False
    if resumable:
        actions.append("resume")
    if run.status in _CANCELLABLE_STATUSES:
        actions.append("cancel")
    return actions
