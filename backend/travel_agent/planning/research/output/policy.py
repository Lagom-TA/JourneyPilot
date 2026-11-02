from __future__ import annotations

from datetime import date
from typing import Any, Literal, Mapping, Sequence

from travel_agent.planning.references import EntityType

ResearchWorkerKind = Literal[
    "destination_researcher",
    "accommodation_researcher",
    "transport_researcher",
]


_WORKER_CANDIDATE_MODELS: dict[ResearchWorkerKind, tuple[tuple[str, str], ...]] = {
    "destination_researcher": (
        ("visit", "VisitCandidate"),
        ("dining", "DiningCandidate"),
    ),
    "accommodation_researcher": (("lodging", "LodgingCandidate"),),
    "transport_researcher": (("transport", "TransportCandidate"),),
}


# 各角色的候选规模下限：短途旅行也保证有差异的基础供给，
# 上限只防单次输出失去可读性，不作为研究质量门槛。
_PACKET_CANDIDATE_LIMIT_FLOORS: dict[ResearchWorkerKind, int] = {
    "destination_researcher": 12,
    "accommodation_researcher": 8,
    "transport_researcher": 8,
}
_PACKET_CANDIDATE_LIMIT_CEILS: dict[ResearchWorkerKind, int] = {
    "destination_researcher": 36,
    "accommodation_researcher": 20,
    "transport_researcher": 24,
}


def _trip_scale(trip_identity: Mapping[str, Any] | None) -> tuple[int, int]:
    """从受控行程身份读取夜数与目的地数，读不到时按最短行程处理。"""
    identity = trip_identity or {}

    def _as_date(value: Any) -> int | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
        return parsed.toordinal()

    start = _as_date(identity.get("start_date"))
    end = _as_date(identity.get("end_date"))
    nights = max(0, (end - start)) if start is not None and end is not None else 0
    destinations = identity.get("destinations")
    destination_count = len(destinations) if isinstance(destinations, list) else 0
    return max(nights, 1), max(destination_count, 1)


def packet_candidate_limit(
    worker_kind: ResearchWorkerKind,
    *,
    trip_identity: Mapping[str, Any] | None = None,
    required_route_scopes: Sequence[Any] = (),
) -> int:
    """结合旅行规模给出本轮 packet 的候选规模参考上限。

    规模随夜数、目的地数和必需跨城段数放宽：旅行越大，允许（也期望）
    研究者带回越充分、越有差异的候选；数字进入提示词作为规模参考，
    不做解析层截断或数量校验。
    """
    nights, destination_count = _trip_scale(trip_identity)
    if worker_kind == "destination_researcher":
        scaled = 3 * nights + 4 * destination_count
    elif worker_kind == "accommodation_researcher":
        scaled = 2 * destination_count + max(1, nights // 2)
    else:
        scaled = 3 * len(required_route_scopes) + 4
    floor = _PACKET_CANDIDATE_LIMIT_FLOORS[worker_kind]
    ceiling = _PACKET_CANDIDATE_LIMIT_CEILS[worker_kind]
    return min(ceiling, max(floor, scaled))


_PLACE_IDENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "visit": (
        "name",
        "place_id",
        "provider_place_type",
        "provider_country_code",
        "address",
    ),
    "dining": (
        "branch_name",
        "place_id",
        "provider_place_type",
        "provider_country_code",
        "address",
    ),
    "lodging": (
        "property_name",
        "place_id",
        "provider_place_type",
        "provider_country_code",
        "address",
    ),
}


_PLACE_NAME_FIELD = {
    "visit": "name",
    "dining": "branch_name",
    "lodging": "property_name",
}


_PLACE_ENTITY_TYPE = {
    "visit": EntityType.VISIT_STOP,
    "dining": EntityType.DINING_STOP,
    "lodging": EntityType.LODGING_STAY,
}


class ResearchPacketOutputError(ValueError):
    """worker 未输出精确的 Research Packet 契约。"""
