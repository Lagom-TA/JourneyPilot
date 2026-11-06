from __future__ import annotations

import contextvars
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Literal, Optional, Tuple
from pydantic import Field, model_validator
from travel_agent.runtime.time import utc_now
from travel_agent.schema import StrictModel


class RunDeadlineSnapshot(StrictModel):
    # 快照内嵌各段秒数，使校验不受之后的配置变更影响。
    draft_id: str = Field(min_length=1)
    planning_authorized_at: datetime
    target_at: datetime
    closeout_at: datetime
    composition_at: datetime
    delivery_deadline_at: datetime
    target_seconds: int = Field(ge=1)
    closeout_seconds: int = Field(ge=1)
    composition_seconds: int = Field(ge=1)
    delivery_deadline_seconds: int = Field(ge=1)
    checkpointed_elapsed_seconds: float = Field(ge=0)
    last_observed_at: datetime

    @model_validator(mode="after")
    def validate_deadlines(self) -> "RunDeadlineSnapshot":
        if any(
            value.tzinfo is None
            for value in (
                self.planning_authorized_at,
                self.target_at,
                self.closeout_at,
                self.composition_at,
                self.delivery_deadline_at,
                self.last_observed_at,
            )
        ):
            raise ValueError("run deadlines must use timezone-aware timestamps")
        if not (
            self.planning_authorized_at
            < self.target_at
            < self.closeout_at
            < self.composition_at
            < self.delivery_deadline_at
        ):
            raise ValueError("run deadlines must be strictly ordered")
        if not (
            self.target_seconds
            < self.closeout_seconds
            < self.composition_seconds
            < self.delivery_deadline_seconds
        ):
            raise ValueError("run deadline windows must be strictly increasing")
        if (
            self.target_at - self.planning_authorized_at
        ).total_seconds() != self.target_seconds:
            raise ValueError("run target must match the snapshot target window")
        if (
            self.closeout_at - self.planning_authorized_at
        ).total_seconds() != self.closeout_seconds:
            raise ValueError("run closeout must match the snapshot closeout window")
        if (
            self.composition_at - self.planning_authorized_at
        ).total_seconds() != self.composition_seconds:
            raise ValueError(
                "run composition must match the snapshot composition window"
            )
        if (
            self.delivery_deadline_at - self.planning_authorized_at
        ).total_seconds() != self.delivery_deadline_seconds:
            raise ValueError(
                "run delivery deadline must match the snapshot delivery window"
            )
        if self.last_observed_at < self.planning_authorized_at:
            raise ValueError("deadline observation predates planning authorization")
        return self


def _windows():
    # 只在封存新快照时读取配置。
    from ..config.loader import get_settings

    return get_settings().run_deadline


def current_target_seconds() -> int:
    return _windows().target_seconds


def current_closeout_seconds() -> int:
    return _windows().closeout_seconds


def current_composition_seconds() -> int:
    return _windows().composition_seconds


def current_delivery_deadline_seconds() -> int:
    return _windows().delivery_seconds


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("run deadline timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


DeadlinePhase = Literal[
    "research", "target_missed", "closeout", "composition_closed", "expired"
]


@dataclass(frozen=True)
class DeadlineObservation:
    """Run 时钟的一次读数。

    ``research`` 与 ``target_missed`` 仍允许发起研究调用；``closeout`` 关闭研究，
    行程编排仍可继续；``composition_closed`` 关闭编排，只保留投影与持久化；
    ``expired`` 表示交付预算已用完。

    调用方应读取下面两个谓词，而不是自行比较 phase：谓词名称就是调用点要问的问题。
    """

    elapsed_seconds: float
    remaining_seconds: float
    phase: DeadlinePhase

    @property
    def research_closed(self) -> bool:
        """worker、修复轮次与 provider 扫描都不能再发起调用。"""
        return self.phase in {"closeout", "composition_closed", "expired"}

    @property
    def composition_closed(self) -> bool:
        """行程编排不能再发起调用，只剩投影。"""
        return self.phase in {"composition_closed", "expired"}


_process_monotonic_anchors: contextvars.ContextVar[Dict[str, float]] = (
    contextvars.ContextVar(
        "process_monotonic_deadline_anchors",
        default={},
    )
)


def clear_process_deadline_anchor(draft_id: Optional[str] = None) -> None:
    anchors = dict(_process_monotonic_anchors.get())
    if draft_id is None:
        anchors.clear()
    else:
        anchors.pop(draft_id, None)
    _process_monotonic_anchors.set(anchors)


def shift_run_deadline(
    snapshot: RunDeadlineSnapshot, extension_seconds: int, *, now: datetime
) -> RunDeadlineSnapshot:
    """把各段时限整体后移，使 Run 暂停期间的墙钟时间不再占用预算。

    进程内的单调锚点同时清除：它按旧基线累计，会把暂停期间重新算进已用时间。
    """
    clear_process_deadline_anchor(snapshot.draft_id)
    shift = timedelta(seconds=extension_seconds)
    return snapshot.model_copy(
        update={
            "target_at": snapshot.target_at + shift,
            "closeout_at": snapshot.closeout_at + shift,
            "composition_at": snapshot.composition_at + shift,
            "delivery_deadline_at": snapshot.delivery_deadline_at + shift,
            "target_seconds": snapshot.target_seconds + extension_seconds,
            "closeout_seconds": snapshot.closeout_seconds + extension_seconds,
            "composition_seconds": snapshot.composition_seconds + extension_seconds,
            "delivery_deadline_seconds": snapshot.delivery_deadline_seconds + extension_seconds,
            "last_observed_at": _as_utc(now),
        }
    )


def renew_deadline_after_interruption(
    snapshot: RunDeadlineSnapshot, *, now: Optional[datetime] = None
) -> Optional[RunDeadlineSnapshot]:
    """恢复被中断的 Run 时，补回从最后一次观测到现在的空档；没有空档时返回 ``None``。

    空档按整秒向上取整，因此每次恢复至多多给不到一秒；多次中断各算各的，
    ``last_observed_at`` 在每次顺延后前移，同一段空档不会被重复补回。
    """
    resumed_at = _as_utc(now or utc_now())
    gap = (resumed_at - _as_utc(snapshot.last_observed_at)).total_seconds()
    if gap <= 0:
        return None
    return shift_run_deadline(snapshot, math.ceil(gap), now=resumed_at)


def renew_deadline_for_composition_retry(
    snapshot: RunDeadlineSnapshot, *, now: Optional[datetime] = None
) -> RunDeadlineSnapshot:
    """重跑行程组合前，让 Run 回到目标完成点，保留原本留给组合与交付的那一段。

    已用时间照实保留；各段时限整体后移，使目标点落在现在。它和研究门的重试顺延
    是同一种语义，所以不依赖“最后一次观测之后空了多久”：失败的 Run 即使在更早
    之前就被观测到过期，也能得到一段可用的时限。
    """
    resumed_at = _as_utc(now or utc_now())
    observed, observation = observe_run_deadline(snapshot, now=resumed_at)
    extension = math.ceil(max(0.0, observation.elapsed_seconds - observed.target_seconds))
    return shift_run_deadline(observed, extension, now=resumed_at)


def observe_run_deadline(
    snapshot: RunDeadlineSnapshot,
    *,
    now: Optional[datetime] = None,
    monotonic_now: Optional[float] = None,
    process_elapsed_seconds: Optional[float] = None,
) -> Tuple[RunDeadlineSnapshot, DeadlineObservation]:
    """推进已持久化的 Deadline 读数，但不重置也不缩短它。

    阶段边界使用 ``snapshot`` 内嵌的秒数，因此之后修改 ``run_deadline`` 配置
    不会改变已有 Run 的阶段判定。
    """
    observed_at = _as_utc(now or utc_now())
    authorization = _as_utc(snapshot.planning_authorized_at)
    wall_elapsed = max(0.0, (observed_at - authorization).total_seconds())
    local_now = time.monotonic() if monotonic_now is None else monotonic_now

    if process_elapsed_seconds is None:
        anchors = dict(_process_monotonic_anchors.get())
        anchor = anchors.get(snapshot.draft_id)
        if anchor is None:
            baseline = max(snapshot.checkpointed_elapsed_seconds, wall_elapsed)
            anchor = local_now - baseline
            anchors[snapshot.draft_id] = anchor
            _process_monotonic_anchors.set(anchors)
        process_elapsed = max(0.0, local_now - anchor)
    else:
        process_elapsed = max(0.0, process_elapsed_seconds)

    elapsed = max(snapshot.checkpointed_elapsed_seconds, wall_elapsed, process_elapsed)
    last_observed = max(_as_utc(snapshot.last_observed_at), observed_at)
    updated = snapshot.model_copy(
        update={
            "checkpointed_elapsed_seconds": round(elapsed, 6),
            "last_observed_at": last_observed,
        }
    )
    if elapsed >= snapshot.delivery_deadline_seconds:
        phase: DeadlinePhase = "expired"
    elif elapsed >= snapshot.composition_seconds:
        phase = "composition_closed"
    elif elapsed >= snapshot.closeout_seconds:
        phase = "closeout"
    elif elapsed >= snapshot.target_seconds:
        phase = "target_missed"
    else:
        phase = "research"
    return updated, DeadlineObservation(
        elapsed_seconds=elapsed,
        remaining_seconds=max(0.0, snapshot.delivery_deadline_seconds - elapsed),
        phase=phase,
    )
