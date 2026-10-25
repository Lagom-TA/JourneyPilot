"""Planning requirements route legs."""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from travel_agent.planning.research.provider_contracts import ProviderRouteLegScope
from typing import AbstractSet
from typing import Any
from typing import Mapping
from typing import Optional
from typing import Sequence
import re


_EXPLICIT_CROSS_DAY_RETURN = re.compile(
    r"跨日|跨夜|次日|翌日|第二天到达|凌晨到达|overnight|red[- ]?eye",
    re.IGNORECASE,
)


def explicit_cross_day_return_required(text: str) -> bool:
    """Classify an explicit cross-calendar-day return requirement."""

    return bool(_EXPLICIT_CROSS_DAY_RETURN.search(text or ""))


def _identity_parts(
    controlled_trip_identity: Mapping[str, Any],
) -> tuple[str, list[str]]:
    origin = controlled_trip_identity.get("origin")
    destinations = controlled_trip_identity.get("destinations")
    origin_id = (
        str(origin.get("place_id") or "").strip() if isinstance(origin, Mapping) else ""
    )
    destination_ids = [
        str(item.get("place_id") or "").strip()
        for item in destinations or ()
        if isinstance(item, Mapping) and str(item.get("place_id") or "").strip()
    ]
    return origin_id, list(dict.fromkeys(destination_ids))


def build_required_long_distance_legs(
    controlled_trip_identity: Mapping[str, Any],
    *,
    cross_day_return_required: bool,
) -> list[ProviderRouteLegScope]:
    """Derive the itinerary chain's exact long-distance leg responsibilities.

    Multi-destination trips are a **chain over the ordered visit list**, not a
    simple round trip.  For ``[origin, *destinations, origin]`` every adjacent
    pair is owed a long-distance leg: ``origin→city_1`` (outbound),
    ``city_i→city_{i+1}`` (inter_destination) for each interior boundary, and
    ``city_M→origin`` (return) when the last destination is not the origin.
    The interior city-to-city legs (e.g. 杭州→苏州 in a 上海→杭州→苏州 trip) are
    built too, not just the outbound and return: they must be researched and bound.

    Each destination's stay is assigned **evenly** over the trip span:
    ``span_days`` is divided across the
    destinations by far-forward positions, with the remainder given to the
    earliest cities.  The handover (inter_destination) leg for ``city_i``
    departs on the **first day of the next city's stay**, so transport research
    happens on the actual handover day.
    """

    origin_id, destination_ids = _identity_parts(controlled_trip_identity)
    if not origin_id or not destination_ids:
        return []
    if origin_id == destination_ids[0] and destination_ids[-1] == origin_id:
        return []
    try:
        start_date = date.fromisoformat(
            str(controlled_trip_identity.get("start_date") or "")[:10]
        )
        end_date = date.fromisoformat(
            str(controlled_trip_identity.get("end_date") or "")[:10]
        )
    except ValueError:
        return []
    if end_date < start_date:
        return []

    span_days = (end_date - start_date).days + 1
    num_destinations = len(destination_ids)

    base, remainder = divmod(span_days, num_destinations)
    per_city: list[int] = [
        base + (1 if i < remainder else 0) for i in range(num_destinations)
    ]

    starts: list[date] = []
    cursor = start_date
    for n in per_city:
        starts.append(cursor)
        cursor += timedelta(days=n)

    legs: list[ProviderRouteLegScope] = [
        ProviderRouteLegScope(
            leg_role="outbound",
            from_place_id=origin_id,
            to_place_id=destination_ids[0],
            service_date=start_date,
            cross_day_required=False,
        )
    ]

    for i in range(num_destinations - 1):
        legs.append(
            ProviderRouteLegScope(
                leg_role="inter_destination",
                from_place_id=destination_ids[i],
                to_place_id=destination_ids[i + 1],
                service_date=starts[i + 1],
                cross_day_required=False,
            )
        )
    if destination_ids[-1] != origin_id:
        legs.append(
            ProviderRouteLegScope(
                leg_role="return",
                from_place_id=destination_ids[-1],
                to_place_id=origin_id,
                service_date=end_date,
                cross_day_required=cross_day_return_required,
            )
        )
    return legs


def missing_long_distance_leg_roles(
    required_legs: Sequence[ProviderRouteLegScope],
    *,
    day_dates: AbstractSet[date],
    dates_with_long_distance: AbstractSet[date],
) -> Optional[list[str]]:
    """Name the required long-distance legs no planned Day ever delivered.

    ``None`` means the round trip is not assessable and every reader must stay
    silent.  Three ways that happens:

    - the Run owes no long-distance leg at all;
    - the composed Days do not even cover a required service date, in which case
      the identity and the itinerary describe different trips and no per-leg
      verdict read from them would be honest;
    - one service date owes more than one leg and carries at least one.  A
      same-day round trip is the real case: both owed legs fall on the trip's
      single date, so "this date has a long-distance leg" cannot separate *one
      of the two arrived* from *both arrived*, and an empty list would assert
      the stronger of the two.  A date that owes two and carries none is still
      assessable — nothing arrived — and both roles are named.

    That silence is deliberately distinct from an empty list, which asserts
    that every owed leg was delivered.

    Naming which of two same-day legs is the missing one needs per-leg delivery
    identity, and the delivered leg does not carry one: its endpoints are
    station-scoped ids minted by the provider binder (``12306:{telecode}``,
    airport codes) while a required leg's endpoints are the city-scoped ids of
    the controlled identity (``osm:relation:…``).  The two never compare equal,
    so matching a delivered leg to a direction would have to be guessed.
    """

    if not required_legs or any(
        leg.service_date not in day_dates for leg in required_legs
    ):
        return None
    owed_per_date: dict[date, int] = {}
    for leg in required_legs:
        owed_per_date[leg.service_date] = owed_per_date.get(leg.service_date, 0) + 1
    if any(
        owed > 1 and service_date in dates_with_long_distance
        for service_date, owed in owed_per_date.items()
    ):
        return None
    return [
        leg.leg_role
        for leg in required_legs
        if leg.service_date not in dates_with_long_distance
    ]
