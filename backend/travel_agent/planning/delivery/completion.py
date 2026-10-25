"""Planning delivery completion."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from travel_agent.planning.delivery.bundle import DeliveryBundle
from travel_agent.planning.outcomes import DeliveryFailureRecord
from travel_agent.planning.state import TravelAgentState


class DeliveryFinalizationError(RuntimeError):
    def __init__(self, record: DeliveryFailureRecord, cause: Exception):
        super().__init__(record.public_message)
        self.record = record
        self.__cause__ = cause


def _terminal_recorded_at(
    state: TravelAgentState, bundle: Optional[DeliveryBundle] = None
) -> datetime:
    """终态时间取持久化的 deadline 观察时刻，不用新的实时时钟。"""

    if state.run_deadline is not None:
        return state.run_deadline.last_observed_at
    if bundle is not None:
        return bundle.manifest.created_at
    if state.minimum_delivery_draft is not None:
        return state.minimum_delivery_draft.planning_authorized_at
    return datetime.now(timezone.utc)


def _require_sealed_completion_generation(state: TravelAgentState) -> None:
    """交付定稿只接受经计划授权启动的 Run，绕过授权直接定稿一律拒绝。

    三项证据缺一不可：本 Run 的密封 Draft、Draft 的授权时刻、与 Draft 绑定的
    deadline 快照。任一缺失说明这次定稿没有对应的用户授权来源。
    """

    draft = state.minimum_delivery_draft
    if (
        draft is None
        or draft.run_id != state.run_id
        or not draft.planning_authorized
        or draft.planning_authorized_at is None
    ):
        raise ValueError(
            "delivery finalizer requires a sealed minimum delivery draft for this run"
        )
    deadline = state.run_deadline
    if (
        deadline is None
        or deadline.draft_id != draft.draft_id
        or deadline.planning_authorized_at != draft.planning_authorized_at
    ):
        raise ValueError(
            "delivery finalizer requires the sealed Draft deadline snapshot"
        )
