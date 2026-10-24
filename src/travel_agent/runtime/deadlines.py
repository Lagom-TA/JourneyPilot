from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Literal, Optional, Tuple
from pydantic import Field, model_validator
from travel_agent.schema import StrictModel


class RunDeadlineSnapshot(StrictModel):
    # Embedded windows keep validation independent of later configuration changes.
    draft_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
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


RUN_DEADLINE_POLICY_VERSION = "run_deadline.v2"


def _windows():
    # Read configuration only when sealing a fresh snapshot.
    from ..config import get_settings

    return get_settings().run_deadline


def current_target_seconds() -> int:
    return _windows().target_seconds


def current_closeout_seconds() -> int:
    return _windows().closeout_seconds


def current_composition_seconds() -> int:
    return _windows().composition_seconds


def current_delivery_deadline_seconds() -> int:
    return _windows().delivery_seconds


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("run deadline timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


DeadlinePhase = Literal[
    "research", "target_missed", "closeout", "composition_closed", "expired"
]


@dataclass(frozen=True)
class DeadlineObservation:
    """One reading of the run clock.

    ``research`` and ``target_missed`` are the windows in which a research call
    may still start.  ``closeout`` closes research while itinerary composition
    stays open; ``composition_closed`` closes that too and leaves only
    projection and persistence; ``expired`` means the delivery budget is gone.

    Read the two predicates rather than comparing phases: they name the question
    each call site is actually asking.
    """

    elapsed_seconds: float
    remaining_seconds: float
    phase: DeadlinePhase

    @property
    def research_closed(self) -> bool:
        """No worker, gate repair or provider sweep may open another call."""
        return self.phase in {"closeout", "composition_closed", "expired"}

    @property
    def composition_closed(self) -> bool:
        """No itinerary composition call may start; only projection remains."""
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


def observe_run_deadline(
    snapshot: RunDeadlineSnapshot,
    *,
    now: Optional[datetime] = None,
    monotonic_now: Optional[float] = None,
    process_elapsed_seconds: Optional[float] = None,
) -> Tuple[RunDeadlineSnapshot, DeadlineObservation]:
    """Advance, but never reset or shorten, a persisted deadline observation.

    Phase boundaries use the seconds embedded on ``snapshot``, so a later change
    to the ``run_deadline`` config cannot reclassify an older run.
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
