"""Runtime run lifecycle."""

from __future__ import annotations

from travel_agent.runtime.run_contracts import RunRecoveryStatus, TripRun, RunExecution
from travel_agent.runtime.run_contracts import TripRunResumePolicy
from travel_agent.runtime.run_contracts import TripRunStatus
from travel_agent.runtime.run_contracts import coerce_status
from typing import Dict
from typing import List
from typing import Optional


TERMINAL_TRIP_RUN_STATUSES: set[TripRunStatus] = {
    TripRunStatus.COMPLETED,
    TripRunStatus.FAILED,
    TripRunStatus.INTERRUPTED,
    TripRunStatus.CANCELLED,
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
    """这个状态还能不能被取消。**表只有一张**：路由的前置判断与
    `available_run_actions` 通报的动作必须读同一份，否则界面亮着的按钮点下去拿 409。
    """

    return coerce_status(status) in _CANCELLABLE_STATUSES


def available_run_actions(
    run: "TripRun",
    execution: Optional["RunExecution"] = None,
) -> List[str]:
    """这个 Run 现在真正能做的动作。

    服务端说一次，客户端不从十几个字段自己推 —— 两处推导必然分叉，而分叉的表现是
    一个亮着的「继续」按钮点下去拿 409。
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
