"""Planning requirements destination scope."""

from __future__ import annotations

from typing import Any
from typing import Iterable
from typing import Mapping
from typing import MutableMapping

from travel_agent.utils.geography import distance_from_destination_km


DESTINATION_DISTANCE_KEY = "destination_distance_km"


MAX_DESTINATION_DISTANCE_KM = 25.0


def is_within_destination(
    latitude: Any,
    longitude: Any,
    destination_latitude: Any,
    destination_longitude: Any,
    *,
    limit_km: float = MAX_DESTINATION_DISTANCE_KM,
) -> bool:
    """Whether a place is close enough to be this destination's own stop.

    Unanswerable is permissive — see :func:`distance_from_destination_km` for why
    an absent point must not read as an out-of-scope one.
    """
    distance = distance_from_destination_km(
        latitude, longitude, destination_latitude, destination_longitude
    )
    return distance is None or distance <= limit_km


def annotate_destination_distance(
    results: Iterable[MutableMapping[str, Any]],
    *,
    destination_latitude: Any,
    destination_longitude: Any,
) -> None:
    """Write each place record's own distance from the destination it was searched for.

    Every layer that hands a server-normalized place record downstream holds both
    halves at that moment — the place and the destination it asked about — and is
    therefore the only layer that can state the distance.  Downstream reads it off
    the record; it is never recomputed, because the trip identity does not travel
    with a tool envelope.

    Written onto a server-normalized record, so it is evidence rather than a model
    claim.  Absent — not zero, not infinity — when either point is missing: an
    unanswerable distance must stay unanswerable all the way down, because "no
    destination point" is a supply gap and "80 km away" is an out-of-scope stop,
    and collapsing them would delete every candidate for a destination whose
    geocode failed.

    Idempotent by construction, so a record that already carries the annotation
    from its own provider is written with the same value rather than two.
    """
    if destination_latitude is None or destination_longitude is None:
        return
    for place in results:
        distance = distance_from_destination_km(
            place.get("latitude"),
            place.get("longitude"),
            destination_latitude,
            destination_longitude,
        )
        if distance is not None:
            place[DESTINATION_DISTANCE_KEY] = round(distance, 3)


def destination_points(
    controlled_trip_identity: Mapping[str, Any] | None,
) -> dict[str, tuple[float, float]]:
    """Omit incomplete coordinates so callers cannot mistake them for a usable point."""
    destinations = (controlled_trip_identity or {}).get("destinations") or []
    points: dict[str, tuple[float, float]] = {}
    for item in destinations:
        if not isinstance(item, Mapping):
            continue
        place_id = str(item.get("place_id") or "")
        latitude, longitude = item.get("latitude"), item.get("longitude")
        if not place_id:
            continue
        if isinstance(latitude, bool) or isinstance(longitude, bool):
            continue
        if not isinstance(latitude, (int, float)) or not isinstance(
            longitude, (int, float)
        ):
            continue
        points[place_id] = (float(latitude), float(longitude))
    return points
