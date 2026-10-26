from __future__ import annotations

from typing import Any, Dict

from travel_agent.planning.research.candidates import (
    DiningCandidate,
    LodgingCandidate,
    TransportCandidate,
    VisitCandidate,
)
from travel_agent.planning.research.catalog import RecommendationCatalog

# 组合提示词的容量上限：每个领域最多向模型展示这么多候选。这是提示词长度
# 约束，不是质量筛选——完整候选集合仍由 JSON Schema 的 candidate_id 枚举
# 允许引用，长距离交通候选优先展示以免锚点缺失。
PROMPT_CANDIDATE_LIMIT_PER_DOMAIN = 8


def prompt_candidate_ids(
    catalog: RecommendationCatalog, *, skeleton_only: bool = False
) -> Dict[str, list[str]]:
    """返回按提示词展示顺序排列的各领域候选 id，数量受容量上限约束。"""
    candidates = catalog.candidate_index()
    by_kind: Dict[str, list[str]] = {
        kind: [] for kind in ("visit", "dining", "transport", "lodging")
    }
    for candidate_id, candidate in candidates.items():
        if candidate.candidate_kind in by_kind:
            by_kind[candidate.candidate_kind].append(candidate_id)

    def display_order(kind: str, candidate_id: str) -> tuple:
        if kind == "transport":
            candidate = candidates[candidate_id]
            if skeleton_only and candidate.transport_class != "long_distance":
                return (2, candidate_id)
            return (
                0 if candidate.transport_class == "long_distance" else 1,
                candidate_id,
            )
        return (0, candidate_id)

    return {
        kind: sorted(ids, key=lambda candidate_id: display_order(kind, candidate_id))[
            :PROMPT_CANDIDATE_LIMIT_PER_DOMAIN
        ]
        for kind, ids in by_kind.items()
    }


def placement_capabilities(
    catalog: RecommendationCatalog, *, skeleton_only: bool = False
) -> list[dict[str, Any]]:
    """只暴露组合合法拓扑所需的强类型落位事实。"""
    candidates = catalog.candidate_index()
    capabilities: list[dict[str, Any]] = []
    for kind, ids in prompt_candidate_ids(
        catalog, skeleton_only=skeleton_only
    ).items():
        for candidate_id in ids:
            candidate = candidates[candidate_id]
            item: dict[str, Any] = {
                "candidate_id": candidate_id,
                "candidate_kind": candidate.candidate_kind,
                "destination_id": candidate.destination_id,
            }
            if isinstance(candidate, VisitCandidate):
                item.update(name=candidate.name, place_id=candidate.place_id)
            elif isinstance(candidate, DiningCandidate):
                item.update(
                    name=candidate.branch_name,
                    place_id=candidate.place_id,
                    meal_types=candidate.meal_types,
                )
            elif isinstance(candidate, TransportCandidate):
                item.update(
                    transport_class=candidate.transport_class,
                    from_place_id=candidate.from_endpoint.place_id,
                    to_place_id=candidate.to_endpoint.place_id,
                    departure_date=(
                        candidate.departure_at.date().isoformat()
                        if candidate.departure_at is not None
                        else None
                    ),
                    arrival_date=(
                        candidate.arrival_at.date().isoformat()
                        if candidate.arrival_at is not None
                        else None
                    ),
                )
            elif isinstance(candidate, LodgingCandidate):
                item.update(
                    name=candidate.property_name,
                    check_in_date=candidate.check_in_date.isoformat(),
                    check_out_date=candidate.check_out_date.isoformat(),
                )
            capabilities.append(item)
    return capabilities
