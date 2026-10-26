from __future__ import annotations

from travel_agent.planning.research.candidates import ResearchCandidate
from travel_agent.planning.research.candidates import VisitCandidate


def candidate_option_availability(candidate: ResearchCandidate) -> str:
    """返回旅行者到场前仍需确认的事项。

    餐饮与住宿候选沿用供应商给出的库存状态，包括 ``"unavailable"``；
    ``SelectionOption`` 会直接拒绝不可用候选，不把它改写成可选项。
    景点没有可预订库存，只表示是否需要提前预约。
    """

    if isinstance(candidate, VisitCandidate):
        return "needs_confirmation" if candidate.reservation_required else "confirmed"
    return str(getattr(candidate, "availability_status", "confirmed"))
