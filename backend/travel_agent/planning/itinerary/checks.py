from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Optional, Sequence

from travel_agent.entities.opening_hours import opening_window_violation
from travel_agent.planning.itinerary.adjacency import (
    _long_distance_anchor,
    day_connector_adjacencies,
    day_lodging_boundaries,
    long_distance_anchor_day_role,
)
from travel_agent.planning.itinerary.bindings import (
    _passed_candidates,
    _topology_place_id,
)
from travel_agent.planning.itinerary.draft import (
    CompositionPlacement,
    DayComposition,
    DiningPlacement,
    ItineraryCompositionDraft,
    ItineraryCompositionError,
    LodgingBoundary,
    PhysicalPlacement,
    VisitPlacement,
    is_authored_placement,
)
from travel_agent.planning.itinerary.models import classify_transport_projection_shape
from travel_agent.planning.research.candidates import (
    DiningCandidate,
    LodgingCandidate,
    ResearchCandidate,
    TransportCandidate,
    VisitCandidate,
)
from travel_agent.planning.research.catalog import RecommendationCatalog

if TYPE_CHECKING:
    from travel_agent.entities.provider_evidence import ProviderRouteLegScope


def _validate_stop_opening_window(
    *,
    day: "DayComposition",
    placement: "PhysicalPlacement",
    candidate: VisitCandidate | DiningCandidate,
) -> None:
    violation = opening_window_violation(
        candidate.opening_window,
        day.date,
        placement.planned_start,
        placement.planned_end,
    )
    if violation:
        name = (
            candidate.name
            if isinstance(candidate, VisitCandidate)
            else candidate.branch_name
        )
        raise ItineraryCompositionError(
            f"day {day.day_id} places {name} {violation} "
            f"({candidate.opening_window}); move the whole stay inside an open interval "
            "before last entry, or choose another candidate"
        )


def validate_long_distance_anchor_day_order(
    day: DayComposition,
    anchors: Sequence[tuple[int, TransportCandidate]],
    physical_placements: Sequence[tuple[int, PhysicalPlacement]],
    days: Sequence[DayComposition],
) -> None:
    # Non-overlap alone does not put a local stop on the correct side of a train.
    if len(anchors) > 2:
        raise ItineraryCompositionError(
            f"day {day.day_id} can carry at most two long-distance anchors "
            "(one that arrives and one that departs, never more)"
        )
    if len(anchors) == 1:
        anchor_position, anchor = anchors[0]
        role = long_distance_anchor_day_role(anchor, day, days)
        arrival_at = anchor.arrival_at
        departure_at = anchor.departure_at
        assert arrival_at is not None and departure_at is not None
        for position, placement in physical_placements:
            if placement.planned_start is None or placement.planned_end is None:
                raise ItineraryCompositionError(
                    f"day {day.day_id} shares a long-distance anchor, so every "
                    f"local placement must carry planned_start and planned_end"
                )
            if role == "arrives":
                if position < anchor_position:
                    raise ItineraryCompositionError(
                        f"day {day.day_id} lists a local stop before the "
                        f"long-distance anchor that arrives at this destination; "
                        f"the anchor must be this day's first placement and every "
                        f"stop must follow it"
                    )
                if placement.planned_start < arrival_at:
                    raise ItineraryCompositionError(
                        f"day {day.day_id} local placement starts "
                        f"{placement.planned_start.isoformat()}, before the "
                        f"traveller arrives at this destination "
                        f"{arrival_at.isoformat()}; move it later or to another day"
                    )
            elif position > anchor_position:
                raise ItineraryCompositionError(
                    f"day {day.day_id} lists a local stop after the long-distance "
                    f"anchor that departs from this destination; the anchor must be "
                    f"this day's last placement and every stop must precede it"
                )
            elif placement.planned_end > departure_at:
                raise ItineraryCompositionError(
                    f"day {day.day_id} local placement ends "
                    f"{placement.planned_end.isoformat()}, after the traveller "
                    f"leaves this destination {departure_at.isoformat()}; move it "
                    f"earlier or to another day"
                )
        return
    pos_arrive, anchor_in = anchors[0]
    pos_depart, anchor_out = anchors[1]
    if not (pos_arrive < pos_depart):
        raise ItineraryCompositionError(
            f"day {day.day_id} with two long-distance anchors must list the one "
            f"that arrives first and the one that departs last"
        )
    arr_at = anchor_in.arrival_at
    dep_at = anchor_out.departure_at
    assert arr_at is not None and dep_at is not None
    for position, placement in physical_placements:
        if placement.planned_start is None or placement.planned_end is None:
            raise ItineraryCompositionError(
                f"day {day.day_id} carries two long-distance anchors, so every "
                f"local placement must carry planned_start and planned_end"
            )
        if not (pos_arrive < position < pos_depart):
            raise ItineraryCompositionError(
                f"day {day.day_id} keeps a local stop outside the corridor "
                f"between the arriving anchor and the departing anchor; "
                f"the arrive anchor must be first, the depart anchor last, "
                f"and every stop between them"
            )
        if placement.planned_start < arr_at:
            raise ItineraryCompositionError(
                f"day {day.day_id} local placement starts "
                f"{placement.planned_start.isoformat()}, before the traveller "
                f"arrives on {arr_at.isoformat()}; move it later"
            )
        if placement.planned_end > dep_at:
            raise ItineraryCompositionError(
                f"day {day.day_id} local placement ends "
                f"{placement.planned_end.isoformat()}, after the traveller "
                f"leaves on {dep_at.isoformat()}; move it earlier"
            )


def validate_placement_skeleton(
    skeleton: ItineraryCompositionDraft,
    catalog: RecommendationCatalog,
    *,
    required_candidate_kinds: Optional[set[str]] = None,
    required_long_distance_legs: Optional[list["ProviderRouteLegScope"]] = None,
    required_leg_scope_ids: Optional[dict[str, str]] = None,
) -> None:
    _validate_placement_content(
        skeleton,
        catalog,
        allow_local_connectors=False,
        required_candidate_kinds=required_candidate_kinds,
        required_long_distance_legs=required_long_distance_legs,
        required_leg_scope_ids=required_leg_scope_ids,
    )


def _validate_placement_content(
    skeleton: ItineraryCompositionDraft,
    catalog: RecommendationCatalog,
    *,
    allow_local_connectors: bool,
    required_candidate_kinds: Optional[set[str]] = None,
    required_long_distance_legs: Optional[list["ProviderRouteLegScope"]] = None,
    required_leg_scope_ids: Optional[dict[str, str]] = None,
) -> None:
    candidates = _passed_candidates(catalog)
    expected_dates = [
        skeleton.days[0].date + timedelta(days=index)
        for index in range(len(skeleton.days))
    ]
    if [day.date for day in skeleton.days] != expected_dates:
        raise ItineraryCompositionError(
            "placement skeleton Day dates must be contiguous"
        )
    day_dates = {day.date for day in skeleton.days}
    admitted_long_distance = {
        candidate_id
        for candidate_id, candidate in candidates.items()
        if isinstance(candidate, TransportCandidate)
        and candidate.transport_class == "long_distance"
    }
    placed_long_distance: set[str] = set()
    placed_physical_kinds: set[str] = set()
    for lodging_id in skeleton.lodging_candidate_ids:
        if not isinstance(candidates.get(lodging_id), LodgingCandidate):
            raise ItineraryCompositionError(
                "placement skeleton lodging must reference an admitted LodgingCandidate"
            )
    for day in skeleton.days:
        physical_count = 0
        long_distance_count = 0
        physical_placements: list[tuple[int, PhysicalPlacement]] = []
        anchors: list[tuple[int, TransportCandidate]] = []
        for position, placement in enumerate(day.placements):
            if is_authored_placement(placement):
                if placement.placement_kind == "transport":
                    if allow_local_connectors:
                        continue
                    raise ItineraryCompositionError(
                        "placement skeleton cannot contain a local transport connector"
                    )
                physical_count += 1
                physical_placements.append((position, placement))
                placed_physical_kinds.add(placement.placement_kind)
                continue
            candidate = candidates.get(placement.candidate_id)
            if placement.placement_kind == "visit":
                if not isinstance(candidate, VisitCandidate):
                    raise ItineraryCompositionError(
                        "placement skeleton visit references another candidate kind"
                    )
                _validate_stop_opening_window(
                    day=day,
                    placement=placement,
                    candidate=candidate,
                )
                physical_count += 1
                physical_placements.append((position, placement))
                placed_physical_kinds.add("visit")
            elif placement.placement_kind == "dining":
                if not isinstance(candidate, DiningCandidate):
                    raise ItineraryCompositionError(
                        "placement skeleton dining references another candidate kind"
                    )
                _validate_stop_opening_window(
                    day=day, placement=placement, candidate=candidate
                )
                if placement.meal_type not in candidate.meal_types:
                    raise ItineraryCompositionError(
                        "placement skeleton dining places a meal the candidate does "
                        f"not serve: {placement.candidate_id} serves "
                        f"{sorted(candidate.meal_types)}, placed as {placement.meal_type}"
                    )
                physical_count += 1
                physical_placements.append((position, placement))
                placed_physical_kinds.add("dining")
            else:
                if not isinstance(candidate, TransportCandidate):
                    raise ItineraryCompositionError(
                        "placement skeleton transport references another candidate kind"
                    )
                if candidate.transport_class != "long_distance":
                    if allow_local_connectors:
                        continue
                    raise ItineraryCompositionError(
                        "placement skeleton cannot contain a local transport candidate"
                    )
                if candidate.departure_at is None or candidate.arrival_at is None:
                    raise ItineraryCompositionError(
                        "long-distance skeleton anchor requires provider departure and arrival times"
                    )
                projection_shape = classify_transport_projection_shape(
                    transport_class=candidate.transport_class,
                    departure_at=candidate.departure_at,
                    arrival_at=candidate.arrival_at,
                    itinerary_dates=day_dates,
                )
                if projection_shape == "outside_itinerary":
                    raise ItineraryCompositionError(
                        "long-distance anchor service dates fall outside the itinerary"
                    )
                service_dates = {
                    candidate.departure_at.date(),
                    candidate.arrival_at.date(),
                }
                if day.date not in service_dates:
                    raise ItineraryCompositionError(
                        f"day {day.day_id} long-distance skeleton placement does not match provider date"
                    )
                long_distance_count += 1
                placed_long_distance.add(candidate.candidate_id)
                anchors.append((position, candidate))
            if candidate is not None and candidate.destination_id != day.destination_id:
                raise ItineraryCompositionError(
                    f"day {day.day_id} placement belongs to another destination"
                )
        if long_distance_count > 2:
            raise ItineraryCompositionError(
                f"day {day.day_id} can select only up to two long-distance "
                f"options (one arriving and one departing)"
            )
        if physical_count and anchors:
            validate_long_distance_anchor_day_order(
                day, anchors, physical_placements, skeleton.days
            )
    if admitted_long_distance and not (admitted_long_distance & placed_long_distance):
        raise ItineraryCompositionError(
            "placement skeleton must select one admitted long-distance anchor"
        )
    if required_long_distance_legs:
        selected_services = [candidates[cid] for cid in placed_long_distance]
        placed_scope_ids = {
            candidate.provider_evidence_scope_id
            for candidate in selected_services
            if candidate.provider_evidence_scope_id
        }
        missing_legs: list[str] = []
        for leg in required_long_distance_legs:
            leg_key = f"{leg.leg_role}@{leg.service_date.isoformat()}"
            leg_scope_id = (
                required_leg_scope_ids.get(leg_key)
                if required_leg_scope_ids is not None
                else None
            )
            if leg_scope_id is not None:
                if leg_scope_id not in placed_scope_ids:
                    missing_legs.append(leg_key)
            elif not any(
                candidate.from_endpoint.place_id == leg.from_place_id
                and candidate.to_endpoint.place_id == leg.to_place_id
                and candidate.departure_at.date() == leg.service_date
                for candidate in selected_services
            ):
                missing_legs.append(leg_key)
        if missing_legs:
            raise ItineraryCompositionError(
                "placement skeleton omits long-distance legs owed on handover "
                f"dates: {', '.join(missing_legs)}"
            )
    missing_required = set(required_candidate_kinds or set()) - placed_physical_kinds
    if missing_required:
        raise ItineraryCompositionError(
            "placement skeleton omits required physical candidate kinds: "
            f"{sorted(missing_required)}"
        )


def _validate_transport_chain(
    *,
    day_id: str,
    candidates: dict[str, ResearchCandidate],
    placements: list[CompositionPlacement],
    start_place_id: Optional[str],
    end_place_id: Optional[str],
    require_local_connector: bool,
) -> None:
    if not placements:
        if require_local_connector:
            raise ItineraryCompositionError(
                f"day {day_id} adjacent physical stops require a local transport connector"
            )
        return

    if any(is_authored_placement(placement) for placement in placements):
        if len(placements) != 1 or not require_local_connector:
            raise ItineraryCompositionError(
                f"day {day_id} authored connector must be the only route between two adjacent stops"
            )
        return

    transport_candidates: list[TransportCandidate] = []
    for placement in placements:
        if placement.placement_kind != "transport":
            raise ItineraryCompositionError(
                f"day {day_id} transport chain contains a non-transport placement"
            )
        candidate = candidates.get(placement.candidate_id)
        if not isinstance(candidate, TransportCandidate):
            raise ItineraryCompositionError(
                "transport placement references another candidate kind"
            )
        if not candidate.from_endpoint.place_id or not candidate.to_endpoint.place_id:
            raise ItineraryCompositionError(
                f"day {day_id} transport chain requires stable endpoint place ids"
            )
        transport_candidates.append(candidate)

    if require_local_connector and not any(
        candidate.transport_class in {"public_transit", "flexible"}
        for candidate in transport_candidates
    ):
        raise ItineraryCompositionError(
            f"day {day_id} long-distance transport cannot replace a local connector"
        )
    if (
        start_place_id is not None
        and transport_candidates[0].from_endpoint.place_id != start_place_id
    ):
        raise ItineraryCompositionError(
            f"day {day_id} transport chain origin does not match the preceding stop"
        )
    for previous, following in zip(transport_candidates, transport_candidates[1:]):
        if previous.to_endpoint.place_id != following.from_endpoint.place_id:
            raise ItineraryCompositionError(
                f"day {day_id} transport chain endpoints are not continuous"
            )
    if (
        end_place_id is not None
        and transport_candidates[-1].to_endpoint.place_id != end_place_id
    ):
        raise ItineraryCompositionError(
            f"day {day_id} transport chain destination does not match the following stop"
        )


def validate_itinerary_transport_topology(
    composition: ItineraryCompositionDraft,
    catalog: RecommendationCatalog,
    *,
    required_candidate_kinds: Optional[set[str]] = None,
    required_long_distance_legs: Optional[list["ProviderRouteLegScope"]] = None,
    required_leg_scope_ids: Optional[dict[str, str]] = None,
) -> None:
    """Validate required content and executable adjacent transport chains."""
    _validate_placement_content(
        composition,
        catalog,
        allow_local_connectors=True,
        required_candidate_kinds=required_candidate_kinds,
        required_long_distance_legs=required_long_distance_legs,
        required_leg_scope_ids=required_leg_scope_ids,
    )
    candidates = _passed_candidates(catalog)

    long_distance_service_groups: dict[
        tuple[str, Optional[date], Optional[date]], set[str]
    ] = {}
    for day in composition.days:
        for placement in day.placements:
            if placement.placement_kind != "transport":
                continue
            candidate = candidates.get(placement.candidate_id)
            if not isinstance(candidate, TransportCandidate):
                continue
            if candidate.transport_class != "long_distance":
                continue
            departure_date = (
                candidate.departure_at.date()
                if candidate.departure_at is not None
                else None
            )
            arrival_date = (
                candidate.arrival_at.date()
                if candidate.arrival_at is not None
                else None
            )
            service_dates = {departure_date, arrival_date} - {None}
            if not service_dates:
                raise ItineraryCompositionError(
                    "long-distance transport requires a provider-bound service date"
                )
            if day.date not in service_dates:
                raise ItineraryCompositionError(
                    f"day {day.day_id} long-distance transport date does not match "
                    "its provider schedule"
                )
            group = (
                candidate.from_endpoint.place_id,
                candidate.to_endpoint.place_id,
                departure_date,
                arrival_date,
            )
            long_distance_service_groups.setdefault(group, set()).add(
                candidate.candidate_id
            )
    competing_groups = {
        group: candidate_ids
        for group, candidate_ids in long_distance_service_groups.items()
        if len(candidate_ids) > 1
    }
    if competing_groups:
        raise ItineraryCompositionError(
            "itinerary can select only one long-distance option per service window: "
            f"{competing_groups}"
        )

    for day in composition.days:
        morning, evening = day_lodging_boundaries(day, composition, candidates)
        node_indexes = [
            index
            for index, placement in enumerate(day.placements)
            if placement.placement_kind in {"visit", "dining"}
            or _long_distance_anchor(placement, candidates) is not None
        ]
        if not node_indexes:
            if any(
                placement.placement_kind == "transport"
                and (
                    placement.authored_route is not None
                    or (
                        isinstance(
                            candidates.get(placement.candidate_id), TransportCandidate
                        )
                        and candidates[placement.candidate_id].transport_class
                        != "long_distance"
                    )
                )
                for placement in day.placements
            ):
                raise ItineraryCompositionError(
                    f"day {day.day_id} local transport requires a physical itinerary stop"
                )
            _validate_transport_chain(
                day_id=day.day_id,
                candidates=candidates,
                placements=list(day.placements),
                start_place_id=None,
                end_place_id=None,
                require_local_connector=False,
            )
            continue

        def _inbound(index: int) -> str:
            """Where the traveller arrives at this node."""
            placement = day.placements[index]
            anchor = _long_distance_anchor(placement, candidates)
            if anchor is not None:
                return anchor.from_endpoint.place_id
            return _topology_place_id(placement, candidates)

        def _outbound(index: int) -> str:
            """Where the traveller leaves this node from."""
            placement = day.placements[index]
            anchor = _long_distance_anchor(placement, candidates)
            if anchor is not None:
                return anchor.to_endpoint.place_id
            return _topology_place_id(placement, candidates)

        first_index = node_indexes[0]
        _validate_transport_chain(
            day_id=day.day_id,
            candidates=candidates,
            placements=list(day.placements[:first_index]),
            start_place_id=candidates[morning.candidate_id].place_id
            if morning is not None
            else None,
            end_place_id=_inbound(first_index),
            require_local_connector=morning is not None
            and candidates[morning.candidate_id].place_id != _inbound(first_index),
        )

        for left_index, right_index in zip(node_indexes, node_indexes[1:]):
            left_placement = day.placements[left_index]
            right_placement = day.placements[right_index]
            left_is_anchor = (
                _long_distance_anchor(left_placement, candidates) is not None
            )
            right_is_anchor = (
                _long_distance_anchor(right_placement, candidates) is not None
            )
            if not left_is_anchor and not isinstance(
                left_placement, (VisitPlacement, DiningPlacement)
            ):
                raise ItineraryCompositionError(
                    f"day {day.day_id} physical topology references an invalid placement"
                )
            if not right_is_anchor and not isinstance(
                right_placement, (VisitPlacement, DiningPlacement)
            ):
                raise ItineraryCompositionError(
                    f"day {day.day_id} physical topology references an invalid placement"
                )
            start_place_id = _outbound(left_index)
            end_place_id = _inbound(right_index)
            between = day.placements[left_index + 1 : right_index]
            _validate_transport_chain(
                day_id=day.day_id,
                candidates=candidates,
                placements=list(between),
                start_place_id=start_place_id,
                end_place_id=end_place_id,
                require_local_connector=start_place_id != end_place_id,
            )

        last_index = node_indexes[-1]
        _validate_transport_chain(
            day_id=day.day_id,
            candidates=candidates,
            placements=list(day.placements[last_index + 1 :]),
            start_place_id=_outbound(last_index),
            end_place_id=candidates[evening.candidate_id].place_id
            if evening is not None
            else None,
            require_local_connector=evening is not None
            and candidates[evening.candidate_id].place_id != _outbound(last_index),
        )
        positions = {id(item): index for index, item in enumerate(day.placements)}
        for left, right, _from, _to, departure, deadline in day_connector_adjacencies(
            day, candidates, composition
        ):
            left_index = (
                -1 if isinstance(left, LodgingBoundary) else positions[id(left)]
            )
            right_index = (
                len(day.placements)
                if isinstance(right, LodgingBoundary)
                else positions[id(right)]
            )
            at = departure
            for connector in day.placements[left_index + 1 : right_index]:
                if connector.authored_route is not None:
                    at += timedelta(minutes=connector.authored_route.duration_minutes)
                else:
                    route = candidates.get(connector.candidate_id)
                    if not isinstance(route, TransportCandidate):
                        continue
                    if route.departure_at is not None and route.departure_at < at:
                        raise ItineraryCompositionError(
                            f"day {day.day_id} connector departs before its preceding activity ends"
                        )
                    at = route.arrival_at or (route.departure_at or at) + timedelta(
                        minutes=route.duration_minutes
                    )
            if at > deadline:
                raise ItineraryCompositionError(
                    f"day {day.day_id} connector reaches its next stop after the planning arrival deadline {deadline.isoformat()}; preserve long-distance boarding buffers"
                )
