"""候选展示名与场所身份。"""

from __future__ import annotations

from travel_agent.planning.delivery.projection_errors import DeliveryProjectionError
from travel_agent.planning.research.candidates import DiningCandidate
from travel_agent.planning.research.candidates import LodgingCandidate
from travel_agent.planning.research.candidates import TransportCandidate
from travel_agent.planning.research.candidates import VisitCandidate


def candidate_display_name(candidate: object) -> str:
    """返回候选对外的唯一名称，屏蔽各领域字段名差异。"""
    if isinstance(candidate, VisitCandidate):
        return candidate.name
    if isinstance(candidate, DiningCandidate):
        return candidate.branch_name
    if isinstance(candidate, LodgingCandidate):
        return candidate.property_name
    if isinstance(candidate, TransportCandidate):
        return f"{candidate.from_endpoint.name} → {candidate.to_endpoint.name}"
    raise DeliveryProjectionError(
        "selection option references an unsupported candidate"
    )


def candidate_place_id(candidate: object) -> str:
    """返回候选绑定的 provider 场所身份，没有时返回空串。

    交通候选表示两端点之间的路线而非单一场所，因此返回 ``""``；按身份取值的
    调用方会丢弃空结果。
    """
    if isinstance(candidate, (VisitCandidate, DiningCandidate, LodgingCandidate)):
        return candidate.place_id
    if isinstance(candidate, TransportCandidate):
        return ""
    raise DeliveryProjectionError(
        "selection option references an unsupported candidate"
    )
