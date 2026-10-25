"""Planning itinerary dispersion."""

from __future__ import annotations

from dataclasses import dataclass
from travel_agent.planning.itinerary.models import StructuredItineraryV2
from travel_agent.planning.references import EntityType
from travel_agent.planning.research.evidence import FactAssertion
from travel_agent.utils.geography import haversine_km
from typing import Mapping
from typing import Optional
from typing import Sequence


LOCAL_TRANSPORT_CLASSES = frozenset({"public_transit", "flexible"})


@dataclass(frozen=True)
class DispersionLeg:
    """One transport leg of a Day, as the two numbers care about it."""

    transport_class: str
    duration_minutes: Optional[int] = None


@dataclass(frozen=True)
class DayDispersion:
    """The measurement of one Day.  Counts travel alongside the two numbers.

    ``local_leg_count`` / ``untimed_local_leg_count`` and
    ``located_point_count`` / ``point_count`` exist so a small number can never
    be read as a good number: 30 minutes over three legs and 30 minutes over
    one timed leg out of three are different Days, and a 2 km span over two
    located stops out of seven is not a compact Day.
    """

    local_leg_minutes: int
    local_leg_count: int
    untimed_local_leg_count: int
    span_km: Optional[float]
    farthest_pair: Optional[tuple[str, str]]
    located_point_count: int
    point_count: int


def day_dispersion(
    points: Sequence[DispersionPoint], legs: Sequence[DispersionLeg]
) -> DayDispersion:
    """Measure one Day from its stops and its transport legs.

    A leg with no duration is counted, not summed as zero — an unpriced leg and
    an instant leg are different facts, and only the count keeps them apart.
    A stop with no coordinates takes no part in the span for the same reason:
    it is reported as unlocated instead of being dropped from the tally.
    """

    local = [leg for leg in legs if leg.transport_class in LOCAL_TRANSPORT_CLASSES]
    timed = [leg.duration_minutes for leg in local if leg.duration_minutes is not None]

    located = [point for point in points if point.is_located]
    span_km: Optional[float] = None
    farthest_pair: Optional[tuple[str, str]] = None
    for index, left in enumerate(located):
        for right in located[index + 1 :]:
            distance = haversine_km(
                float(left.latitude),
                float(left.longitude),
                float(right.latitude),
                float(right.longitude),
            )
            if span_km is None or distance > span_km:
                span_km = distance
                farthest_pair = (left.label, right.label)

    return DayDispersion(
        local_leg_minutes=sum(timed),
        local_leg_count=len(local),
        untimed_local_leg_count=len(local) - len(timed),
        span_km=span_km,
        farthest_pair=farthest_pair,
        located_point_count=len(located),
        point_count=len(points),
    )


def entity_coordinates(
    entity: object, fact_index: Mapping[str, FactAssertion]
) -> tuple[Optional[float], Optional[float]]:
    """Where a stop is, from the only two layers allowed to say so.

    An authored entry carries the coordinates the place provider resolved for it
    onto the stop itself; a candidate-backed stop leaves them unset and its
    location lives in the verified coordinate facts its lineage cites.  This is
    the rule the map projection renders and therefore the rule any other reader
    of the same location has to use — there is no third source and no guess.
    """

    latitude = getattr(entity, "latitude", None)
    longitude = getattr(entity, "longitude", None)
    if latitude is not None and longitude is not None:
        return latitude, longitude
    lineage = getattr(entity, "lineage", None)
    assertion_ids = getattr(lineage, "fact_assertion_ids", ())
    return verified_coordinate_pair(assertion_ids, fact_index)


def itinerary_dispersion(
    itinerary: StructuredItineraryV2, fact_index: Mapping[str, FactAssertion]
) -> list[tuple[str, DayDispersion]]:
    """Measure every Day of a materialized itinerary, in Day order.

    The Day's timeline is the authority on what belongs to it: an entity is on
    the Day it is projected onto, which is also the Day whose connectors were
    built for it.
    """

    stops: dict[str, object] = {}
    for stop in itinerary.visit_stops:
        stops[stop.item_id] = stop
    for stop in itinerary.dining_stops:
        stops[stop.item_id] = stop
    for stay in itinerary.lodging_stays:
        stops[stay.stay_id] = stay
    legs = {leg.transport_leg_id: leg for leg in itinerary.transport_legs}

    measured: list[tuple[str, DayDispersion]] = []
    for day in itinerary.day_plans:
        points: list[DispersionPoint] = []
        day_legs: list[DispersionLeg] = []
        for entry in day.timeline:
            if entry.entity_type == EntityType.TRANSPORT_LEG:
                leg = legs.get(entry.entity_id)
                if leg is not None:
                    day_legs.append(
                        DispersionLeg(
                            transport_class=leg.transport_class,
                            duration_minutes=leg.duration_minutes,
                        )
                    )
                continue
            stop = stops.get(entry.entity_id)
            if stop is None:
                continue
            latitude, longitude = entity_coordinates(stop, fact_index)
            points.append(
                DispersionPoint(
                    label=getattr(stop, "name", entry.entity_id),
                    latitude=latitude,
                    longitude=longitude,
                )
            )
        measured.append((day.day_id, day_dispersion(points, day_legs)))
    return measured


@dataclass(frozen=True)
class DispersionPoint:
    """One stop of a Day, with whatever coordinates were resolvable for it."""

    label: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @property
    def is_located(self) -> bool:
        return self.latitude is not None and self.longitude is not None


def verified_coordinate_pair(
    assertion_ids: Sequence[str], fact_index: Mapping[str, FactAssertion]
) -> tuple[Optional[float], Optional[float]]:
    """The verified latitude/longitude an entity's lineage supports, or neither.

    Half a pair is not a location, so a lone verified latitude yields nothing.
    """

    values: dict[str, float] = {}
    for assertion_id in assertion_ids:
        fact = fact_index.get(assertion_id)
        if (
            fact is None
            or fact.status != "verified"
            or fact.field_path not in {"latitude", "longitude"}
        ):
            continue
        value = fact.asserted_value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        coordinate = float(value)
        if fact.field_path == "latitude" and -90 <= coordinate <= 90:
            values["latitude"] = coordinate
        if fact.field_path == "longitude" and -180 <= coordinate <= 180:
            values["longitude"] = coordinate
    if set(values) != {"latitude", "longitude"}:
        return None, None
    return values["latitude"], values["longitude"]
