"""产品策略。"""

from __future__ import annotations

from travel_agent.config.seeds.trip_planner import validated_trip_planner_seed
from typing import Any
from typing import Mapping


def _style_markers(
    option_ids: set[str], extra: set[str] | None = None
) -> frozenset[str]:
    markers = {item.casefold() for item in (extra or set())}
    config = validated_trip_planner_seed()
    for option in [*config.primary_styles, *config.secondary_interests]:
        if option.id not in option_ids:
            continue
        markers.add(option.id.casefold())
        markers.add(option.label.casefold())
        markers.update(keyword.casefold() for keyword in option.inference_keywords)
    return frozenset(markers)


_FOOD_STYLE_MARKERS = _style_markers({"food", "local_food"})


_VISIT_STYLE_MARKERS = _style_markers(
    {
        "balanced",
        "culture",
        "outdoors",
        "hidden_gems",
        "shopping",
        "nightlife",
        "photography",
    },
    {
        "classic sights",
        "classic_sights",
        "sightseeing",
        "文化",
        "景点",
        "经典景点",
        "观光",
    },
)


def style_selected_physical_candidate_kinds(
    controlled_trip_identity: Mapping[str, Any] | None,
) -> set[str]:
    """返回用户风格选择涉及的实体领域。

    这是引导研究方向的兴趣信号，不构成交付义务：结果中缺少某个领域时，模型按
    研究缺口处理，不视为违反契约。
    """
    identity = controlled_trip_identity or {}
    style = identity.get("style")
    if not isinstance(style, Mapping):
        return set()
    values = [style.get("primary"), *(style.get("secondary_interests") or [])]
    normalized = {
        str(value).strip().casefold()
        for value in values
        if isinstance(value, str) and value.strip()
    }
    selected: set[str] = set()
    if any(
        marker == value or marker in value
        for marker in _FOOD_STYLE_MARKERS
        for value in normalized
    ):
        selected.add("dining")
    if any(
        marker == value or marker in value
        for marker in _VISIT_STYLE_MARKERS
        for value in normalized
    ):
        selected.add("visit")
    return selected
