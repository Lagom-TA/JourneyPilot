from __future__ import annotations

from typing import Dict

from travel_agent.planning.research.catalog import RecommendationCatalog

def prompt_candidate_ids(
    catalog: RecommendationCatalog, *, skeleton_only: bool = False
) -> Dict[str, list[str]]:
    """返回按提示词展示顺序排列的全部候选 id。

    骨架阶段与组合 JSON Schema 保持同一范围：市内交通候选此时不在
    可引用枚举里，提示词同样不展示，避免模型引用无法通过的 candidate_id。
    """
    candidates = catalog.candidate_index()
    by_kind: Dict[str, list[str]] = {
        kind: [] for kind in ("visit", "dining", "transport", "lodging")
    }
    for candidate_id, candidate in candidates.items():
        if candidate.candidate_kind not in by_kind:
            continue
        if (
            skeleton_only
            and candidate.candidate_kind == "transport"
            and candidate.transport_class != "long_distance"
        ):
            continue
        by_kind[candidate.candidate_kind].append(candidate_id)

    def display_order(kind: str, candidate_id: str) -> tuple:
        if kind == "transport":
            candidate = candidates[candidate_id]
            return (
                0 if candidate.transport_class == "long_distance" else 1,
                candidate_id,
            )
        return (0, candidate_id)

    return {
        kind: sorted(ids, key=lambda candidate_id: display_order(kind, candidate_id))
        for kind, ids in by_kind.items()
    }

