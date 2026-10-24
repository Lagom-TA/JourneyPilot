from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from .requirements.inputs import MinimumDeliveryDraft
from ..runtime.deadlines import (
    RunDeadlineSnapshot,
    RUN_DEADLINE_POLICY_VERSION,
    _as_utc,
    current_target_seconds,
    current_closeout_seconds,
    current_composition_seconds,
    current_delivery_deadline_seconds,
)


def build_run_deadline_snapshot(
    draft: MinimumDeliveryDraft,
    *,
    authorized_at: Optional[datetime] = None,
    policy_version: str = RUN_DEADLINE_POLICY_VERSION,
) -> RunDeadlineSnapshot:
    """Bind one sealed Draft to immutable deadline audit points."""
    if not draft.planning_authorized or draft.planning_authorized_at is None:
        raise ValueError("run deadline requires a sealed minimum delivery draft")
    authorization = _as_utc(authorized_at or draft.planning_authorized_at)
    if authorization != _as_utc(draft.planning_authorized_at):
        raise ValueError("run deadline authorization time must match the sealed draft")
    target_seconds = current_target_seconds()
    closeout_seconds = current_closeout_seconds()
    composition_seconds = current_composition_seconds()
    delivery_deadline_seconds = current_delivery_deadline_seconds()
    return RunDeadlineSnapshot(
        draft_id=draft.draft_id,
        policy_version=policy_version,
        planning_authorized_at=authorization,
        target_at=authorization + timedelta(seconds=target_seconds),
        closeout_at=authorization + timedelta(seconds=closeout_seconds),
        composition_at=authorization + timedelta(seconds=composition_seconds),
        delivery_deadline_at=authorization
        + timedelta(seconds=delivery_deadline_seconds),
        target_seconds=target_seconds,
        closeout_seconds=closeout_seconds,
        composition_seconds=composition_seconds,
        delivery_deadline_seconds=delivery_deadline_seconds,
        checkpointed_elapsed_seconds=0.0,
        last_observed_at=authorization,
    )
