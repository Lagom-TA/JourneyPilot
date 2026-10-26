"""Planning requirements product policy."""

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
    """Return the physical domains the user's style selection asks about.

    This is the interest signal that steers what research goes looking for.
    It carries no delivery obligation: a domain missing from the result is a
    research gap the model reasons about, not a contract breach.
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
