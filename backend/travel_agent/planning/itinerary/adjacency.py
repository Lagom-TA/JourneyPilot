from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal, Mapping, Optional, Sequence

from travel_agent.planning.itinerary.time_buffers import planned_alighting_buffer_minutes, planned_boarding_buffer_minutes
from travel_agent.planning.itinerary.bindings import (
    placement_display_name,
    placement_place_id,
)
from travel_agent.planning.itinerary.draft import (
    ChainNode,
    CompositionPlacement,
    DayComposition,
    ItineraryCompositionDraft,
    ItineraryCompositionError,
    LodgingBoundary,
)
from travel_agent.planning.research.candidates import (
    LodgingCandidate,
    ResearchCandidate,
    TransportCandidate,
)
from travel_agent.planning.transport import TransportEndpoint


def long_distance_anchor_day_role(
    candidate: TransportCandidate,
    day: DayComposition,
    days: Sequence[DayComposition],
) -> Literal["arrives", "departs"]:
    # Cross-night dates take precedence; same-day direction follows the city stay.
    assert candidate.departure_at is not None and candidate.arrival_at is not None
    departure_date = candidate.departure_at.date()
    arrival_date = candidate.arrival_at.date()
    if departure_date != arrival_date:
        return "arrives" if day.date == arrival_date else "departs"
    first_date_at_destination = min(
        other.date for other in days if other.destination_id == day.destination_id
    )
    return "arrives" if day.date == first_date_at_destination else "departs"


def _long_distance_anchor(
    placement: CompositionPlacement,
    candidates: Mapping[str, ResearchCandidate],
) -> Optional[TransportCandidate]:
    """The admitted long-distance leg this placement selects, if it is one."""

    if placement.placement_kind != "transport" or not placement.candidate_id:
        return None
    candidate = candidates.get(placement.candidate_id)
    if (
        isinstance(candidate, TransportCandidate)
        and candidate.transport_class == "long_distance"
        and candidate.departure_at is not None
        and candidate.arrival_at is not None
    ):
        return candidate
    return None


def day_chain_node_pairs(
    day: DayComposition,
    candidates: Optional[Mapping[str, ResearchCandidate]] = None,
    composition: Optional[ItineraryCompositionDraft] = None,
) -> list[tuple[ChainNode, ChainNode]]:
    nodes: list[ChainNode] = [
        placement
        for placement in day.placements
        if placement.placement_kind in {"visit", "dining"}
        or (
            placement.placement_kind == "transport"
            and (
                candidates is None
                or _long_distance_anchor(placement, candidates) is not None
            )
        )
    ]
    if composition is not None and candidates is not None:
        morning, evening = day_lodging_boundaries(day, composition, candidates)
        if morning is not None:
            nodes.insert(0, morning)
        if evening is not None:
            nodes.append(evening)
    return list(zip(nodes, nodes[1:]))


def selected_lodging_by_night(
    composition: ItineraryCompositionDraft,
    candidates: Mapping[str, ResearchCandidate],
) -> dict[date, LodgingCandidate]:
    """Use the same stay-window selection as workspace materialization."""
    nights: dict[date, LodgingCandidate] = {}
    selected_windows: set[tuple[str, date, date]] = set()
    for candidate_id in composition.lodging_candidate_ids:
        candidate = candidates.get(candidate_id)
        if not isinstance(candidate, LodgingCandidate):
            continue
        window = _destination_stay_window(
            composition,
            candidate.destination_id,
            candidate.check_in_date,
            candidate.check_out_date,
        )
        if window is None:
            continue
        identity = (candidate.destination_id, *window)
        if identity in selected_windows:
            continue
        selected_windows.add(identity)
        night = window[0]
        while night < window[1]:
            if night in nights and nights[night].place_id != candidate.place_id:
                raise ItineraryCompositionError(
                    f"multiple lodging bases selected for night {night}"
                )
            nights[night] = candidate
            night += timedelta(days=1)
    return nights


def day_lodging_boundaries(
    day: DayComposition,
    composition: ItineraryCompositionDraft,
    candidates: Mapping[str, ResearchCandidate],
) -> tuple[Optional[LodgingBoundary], Optional[LodgingBoundary]]:
    nodes = [
        item
        for item in day.placements
        if item.placement_kind in {"visit", "dining"}
        or _long_distance_anchor(item, candidates) is not None
    ]
    if not nodes:
        return None, None
    nights = selected_lodging_by_night(composition, candidates)
    morning_candidate = nights.get(day.date - timedelta(days=1))
    evening_candidate = nights.get(day.date)
    first, last = nodes[0], nodes[-1]
    first_anchor = _long_distance_anchor(first, candidates)
    last_anchor = _long_distance_anchor(last, candidates)
    if first_anchor is not None:
        if long_distance_anchor_day_role(
            first_anchor, day, composition.days
        ) == "arrives" and (
            morning_candidate is None
            or morning_candidate.destination_id == day.destination_id
        ):
            morning_candidate = None
        first_at = first_anchor.departure_at - timedelta(
            minutes=planned_boarding_buffer_minutes(first_anchor.selected_mode)
        )
    else:
        first_at = getattr(first, "planned_start", None)
    if last_anchor is not None:
        if (
            long_distance_anchor_day_role(last_anchor, day, composition.days)
            == "departs"
        ):
            evening_candidate = None
        last_at = last_anchor.arrival_at
    else:
        last_at = getattr(last, "planned_end", None)
    morning = evening = None
    if morning_candidate is not None and first_at is not None:
        departure = max(
            first_at.replace(hour=0, minute=0, second=0, microsecond=0),
            first_at - timedelta(minutes=90),
        )
        morning = LodgingBoundary(
            morning_candidate.candidate_id, "morning", departure, departure
        )
    if evening_candidate is not None and last_at is not None:
        deadline = min(
            last_at.replace(hour=23, minute=59, second=0, microsecond=0),
            last_at + timedelta(minutes=90),
        )
        evening = LodgingBoundary(
            evening_candidate.candidate_id, "evening", deadline, deadline
        )
    return morning, evening


def day_connector_adjacencies(
    day: DayComposition,
    candidates: Mapping[str, ResearchCandidate],
    composition: Optional[ItineraryCompositionDraft] = None,
) -> list[
    tuple[CompositionPlacement, CompositionPlacement, str, str, datetime, datetime]
]:

    adjacencies: list[
        tuple[CompositionPlacement, CompositionPlacement, str, str, datetime, datetime]
    ] = []
    for left, right in day_chain_node_pairs(day, candidates, composition):
        left_anchor = _long_distance_anchor(left, candidates)
        right_anchor = _long_distance_anchor(right, candidates)
        if left_anchor is not None:
            from_place_id = left_anchor.to_endpoint.place_id
            departure_time = left_anchor.arrival_at + timedelta(
                minutes=planned_alighting_buffer_minutes(left_anchor.selected_mode)
            )
        elif isinstance(left, LodgingBoundary):
            from_place_id = candidates[left.candidate_id].place_id
            departure_time = left.planned_end
        else:
            from_place_id = placement_place_id(left, candidates)
            departure_time = getattr(left, "planned_end", None)
        if right_anchor is not None:
            to_place_id = right_anchor.from_endpoint.place_id
            latest_arrival_time = right_anchor.departure_at - timedelta(
                minutes=planned_boarding_buffer_minutes(right_anchor.selected_mode)
            )
        elif isinstance(right, LodgingBoundary):
            to_place_id = candidates[right.candidate_id].place_id
            latest_arrival_time = right.planned_start
        else:
            to_place_id = placement_place_id(right, candidates)
            latest_arrival_time = getattr(right, "planned_start", None)
        if departure_time is None or latest_arrival_time is None:
            raise ItineraryCompositionError(
                f"day {day.day_id} adjacent skeleton placements require scheduled times"
            )
        if not from_place_id or not to_place_id:
            raise ItineraryCompositionError(
                f"day {day.day_id} adjacency requires stable endpoint place ids"
            )
        if from_place_id == to_place_id:
            if departure_time > latest_arrival_time:
                raise ItineraryCompositionError(
                    f"day {day.day_id} same-place occurrences overlap"
                )
            continue
        adjacencies.append(
            (
                left,
                right,
                from_place_id,
                to_place_id,
                departure_time,
                latest_arrival_time,
            )
        )
    return adjacencies


def _chain_endpoint(
    node: ChainNode,
    candidates: Mapping[str, ResearchCandidate],
    *,
    leaving: bool,
) -> TransportEndpoint:
    if isinstance(node, LodgingBoundary):
        lodging = candidates[node.candidate_id]
        return TransportEndpoint(
            name=lodging.property_name,
            place_id=lodging.place_id,
        )
    anchor = _long_distance_anchor(node, candidates)
    if anchor is not None:
        return anchor.to_endpoint if leaving else anchor.from_endpoint
    place = node.authored_place
    return TransportEndpoint(
        name=placement_display_name(node, candidates),
        place_id=placement_place_id(node, candidates),
        latitude=place.resolved_latitude if place else None,
        longitude=place.resolved_longitude if place else None,
    )


def _destination_nights(
    composition: "ItineraryCompositionDraft", destination_id: str
) -> tuple[list[date], list[date]]:

    dates = sorted({day.date for day in composition.days})
    if not dates:
        return [], []
    trip_last = dates[-1]
    mine: list[date] = []
    others: list[date] = []
    for day in composition.days:
        if day.date == trip_last:
            continue
        (mine if day.destination_id == destination_id else others).append(day.date)
    return sorted(mine), sorted(others)


def _destination_stay_window(
    composition: "ItineraryCompositionDraft",
    destination_id: str,
    check_in: date,
    check_out: date,
) -> Optional[tuple[date, date]]:

    mine, others = _destination_nights(composition, destination_id)
    if not mine:
        return None
    authored: list[date] = []
    cursor = check_in
    while cursor < check_out:
        authored.append(cursor)
        cursor += timedelta(days=1)
    mine_set, others_set = set(mine), set(others)
    kept = [night for night in authored if night in mine_set] or mine
    start = kept[0]
    last_owed = kept[-1] + timedelta(days=1)
    if any(night in others_set for night in authored):
        return start, last_owed
    return start, max(check_out, last_owed)
