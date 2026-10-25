"""Planning requirements product policy."""

from __future__ import annotations

from travel_agent.preset.product_config import validated_trip_planner_seed
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


def destinations_are_cn_only(
    controlled_trip_identity: Mapping[str, Any] | None,
) -> bool:
    """True only on positive evidence that every controlled destination is in CN.

    The CN / non-CN split is the one place seam the product keeps: domestic trips
    reach dining through the amap POI provider, everything else through OSM plus
    an open web review page.  A trip whose destinations are missing, empty, or
    only partly CN gets ``False`` — the gate must never read an absent field as
    "domestic".
    """
    destinations = (controlled_trip_identity or {}).get("destinations")
    if not isinstance(destinations, (list, tuple)) or not destinations:
        return False
    codes: set[str] = set()
    for item in destinations:
        if not isinstance(item, Mapping):
            return False
        code = str(item.get("country_code") or "").strip().casefold()
        if not code:
            return False
        codes.add(code)
    return codes == {"cn"}


def style_selected_physical_candidate_kinds(
    controlled_trip_identity: Mapping[str, Any] | None,
) -> set[str]:
    """Return the physical domains the user's style selection asks about.

    Country-blind and promise-blind: this is the *interest* signal, used to decide
    what a worker should go looking for.  What the product owes the user is
    ``required_physical_candidate_kinds`` below.
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


_BASELINE_PHYSICAL_KINDS = frozenset({"visit"})


def required_physical_candidate_kinds(
    controlled_trip_identity: Mapping[str, Any] | None,
) -> set[str]:
    """Return non-compensating physical domains promised by product choices.

    "Promised" is the strong word: every domain in this set is one the product
    must deliver, so Candidate Gate opens a research gap for it, spends a
    targeted-research attempt on it, and lets a run end incomplete rather than
    ship without it.

    Visit is promised unconditionally — see ``_BASELINE_PHYSICAL_KINDS`` for why
    it is not read out of the style text.  Dining is promised only for CN-only
    destinations, where the amap POI provider grounds a restaurant identity plus
    its quality evidence deterministically.  Abroad, dining is best-effort: the
    worker still looks for it (see
    ``destination_researcher.node.resolve_discovery_candidate_kinds``) and
    delivers whatever it can ground, but a run that finds none stays silent
    instead of burning repair budget on a domain no provider seam can close.

    Never empty, and that is the point: an empty promise set is a contract that
    an itinerary with nothing in it satisfies.
    """
    selected = style_selected_physical_candidate_kinds(controlled_trip_identity)
    selected |= set(_BASELINE_PHYSICAL_KINDS)
    if not destinations_are_cn_only(controlled_trip_identity):
        selected.discard("dining")
    return selected


def discovery_physical_candidate_kinds(
    controlled_trip_identity: Mapping[str, Any] | None,
) -> set[str]:
    """Return every physical domain worth grounding: the promise plus the interest.

    The invariant this exists to hold is ``discovery ⊇ required``.  A domain the
    gate enforces but the deterministic preflight never goes looking for is the
    worst of both: the packet is rejected for missing something nothing was sent
    to find, and the repair budget is spent re-asking for it.  That is the
    half-fix shape, and making Visit an unconditional promise is
    exactly the change that could have opened it — ``轻松慢游`` and
    ``亲子友好`` select no domain at all, so before this function the enforced set
    would have grown a member the discovery set did not have.

    Stating it as a union makes the invariant structural rather than a property
    the two keyword paths happened to share.  The one member discovery adds is
    non-CN dining: delivering a restaurant nobody promised costs a few queries,
    and finding none costs nothing downstream.
    """
    return required_physical_candidate_kinds(
        controlled_trip_identity
    ) | style_selected_physical_candidate_kinds(controlled_trip_identity)
