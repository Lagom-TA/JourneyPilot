from __future__ import annotations

from typing import Dict

from travel_agent.planning.research.candidates import TransportCandidate
from travel_agent.planning.research.catalog import RecommendationCatalog


def selected_ids_by_kind(
    catalog: RecommendationCatalog,
    *,
    skeleton_only: bool = False,
) -> Dict[str, list[str]]:
    """按 catalog 稳定顺序列出各域的候选 id。

    这是组合输出的反伪造许可集：落位只能引用 catalog 实际包含的候选 id。
    集合是全量的，不受提示词展示上限影响。
    """
    candidate_index = catalog.candidate_index()
    return {
        kind: sorted(
            (
                candidate_id
                for candidate_id, candidate in candidate_index.items()
                if candidate.candidate_kind == kind
                and not (
                    skeleton_only
                    and kind == "transport"
                    and isinstance(candidate_index[candidate_id], TransportCandidate)
                    and candidate_index[candidate_id].transport_class != "long_distance"
                )
            ),
        )
        for kind in ("visit", "dining", "transport", "lodging")
    }


def authoring_domains(
    catalog: RecommendationCatalog,
    *,
    day_count: int,
    skeleton_only: bool = False,
) -> set[str]:
    """在整个行程选中供给稀疏时，放开对应域的自主撰写。"""
    ids_by_kind = selected_ids_by_kind(catalog, skeleton_only=skeleton_only)
    domains = {
        kind
        for kind in ("visit", "dining")
        if len(ids_by_kind[kind]) < max(day_count, 1)
    }
    if not skeleton_only and not ids_by_kind["transport"]:
        domains.add("transport")
    return domains
