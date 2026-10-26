from __future__ import annotations

from datetime import date, timedelta
from typing import List

from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.requirements.inputs import UserInputAnchor


def controlled_day_dates(state: TravelAgentState) -> List[date]:
    """行程窗口覆盖的每一天：优先取受控行程身份，其次取天气上下文。"""
    identity = state.controlled_trip_identity or {}
    start = end = None
    if isinstance(identity, dict):
        try:
            start = date.fromisoformat(str(identity.get("start_date") or "")[:10])
            end = date.fromisoformat(str(identity.get("end_date") or "")[:10])
        except ValueError:
            start = end = None
    if (
        start is None or end is None or end < start
    ) and state.weather_context is not None:
        start = state.weather_context.trip_start_date
        end = state.weather_context.trip_end_date
    if start is None or end is None or end < start:
        return []
    return [start + timedelta(days=index) for index in range((end - start).days + 1)]


def itinerary_day_count(state: TravelAgentState) -> int:
    """行程窗口内的天数，用于决定允许撰写的领域。"""
    return len(controlled_day_dates(state))


def _draft_user_input_anchors(state: TravelAgentState) -> List[UserInputAnchor]:
    """把受控输入的锚点带进组合后的 Workspace。"""
    draft = state.minimum_delivery_draft
    if draft is None:
        return []
    return list(draft.user_input_anchors)
