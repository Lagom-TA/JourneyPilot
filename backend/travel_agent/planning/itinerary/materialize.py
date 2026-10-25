from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Mapping, Optional

from travel_agent.planning.research.selection_contracts import CandidateSelectionPlan
from travel_agent.planning.itinerary.mutation_contracts import CompositionMutation
from travel_agent.planning.requirements.place_names import CONTROLLED_DESTINATION_ANCHOR_PREFIX, controlled_public_place_name
from travel_agent.planning.itinerary.day_themes import derive_day_theme
from travel_agent.planning.requirements.snapshot_contracts import IntentContractSnapshot
from travel_agent.planning.research.reference_service_contracts import ProviderReferenceService
from travel_agent.planning.delivery.reference_service_presentation import reference_service_note
from travel_agent.planning.transport_semantics import count_service_transfers
from travel_agent.planning.itinerary.highlights import derive_trip_highlights
from travel_agent.planning.costs.coverage import (
    build_cost_coverage_summary,
    itinerary_price_components,
)
from travel_agent.planning.itinerary.adjacency import (
    _chain_endpoint,
    _destination_stay_window,
    _long_distance_anchor,
    day_lodging_boundaries,
)
from travel_agent.planning.itinerary.bindings import (
    _authored_lineage,
    _lineage,
    _located_authored_place,
    _passed_candidates,
)
from travel_agent.planning.itinerary.checks import validate_itinerary_transport_topology
from travel_agent.planning.itinerary.draft import (
    CompositionPlacement,
    DayComposition,
    ItineraryCompositionDraft,
    ItineraryCompositionError,
    _stable_id,
    is_authored_placement,
    placement_occurrence_key,
)
from travel_agent.planning.itinerary.models import (
    DayPlanV2,
    DiningStop,
    LodgingStay,
    StructuredItineraryV2,
    TimelineEntryRef,
    TransportLeg,
    VisitStop,
    classify_transport_projection_shape,
)
from travel_agent.planning.itinerary.options import SelectionSlot
from travel_agent.planning.itinerary.selection import _slot, _transport_slots
from travel_agent.planning.references import EntityType
from travel_agent.planning.requirements.inputs import UserInputAnchor
from travel_agent.planning.research.candidates import (
    DiningCandidate,
    LodgingCandidate,
    ResearchCandidate,
    TransportCandidate,
    VisitCandidate,
)
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.planning.transport import TransportMode, TransportSegment
from travel_agent.planning.workspace import TripWorkspaceV2

if TYPE_CHECKING:
    from travel_agent.planning.research.provider_contracts import ProviderRouteLegScope


def _total_budget_cap_cny(anchors: Optional[list[UserInputAnchor]]) -> Optional[float]:
    for anchor in anchors or []:
        if anchor.input_kind != "hard_constraint" or not isinstance(
            anchor.value, Mapping
        ):
            continue
        if str(anchor.value.get("category") or "") != "budget_cap":
            continue
        params = anchor.value.get("params")
        if not isinstance(params, Mapping):
            continue
        if (
            str(params.get("currency") or "CNY").upper() != "CNY"
            or str(params.get("per") or "") != "total"
        ):
            continue
        amount = params.get("amount")
        if isinstance(amount, (int, float)) and amount >= 0:
            return float(amount)
    return None


def _controlled_destination_names(
    anchors: Optional[list[UserInputAnchor]],
) -> dict[str, str]:
    names: dict[str, str] = {}
    for anchor in anchors or []:
        if (
            anchor.input_kind != "controlled_identity"
            or not anchor.field_path.startswith(CONTROLLED_DESTINATION_ANCHOR_PREFIX)
            or not isinstance(anchor.value, Mapping)
        ):
            continue
        destination_id = str(anchor.value.get("place_id") or "").strip()
        public_name = controlled_public_place_name(anchor.value)
        if destination_id and public_name:
            names[destination_id] = public_name
    return names


def _authored_transport_leg(
    *,
    day: DayComposition,
    index: int,
    candidates: Mapping[str, ResearchCandidate],
    composition: ItineraryCompositionDraft,
) -> TransportLeg:
    placement = day.placements[index]
    node_kinds = {"visit", "dining"}

    def _node(items: list[CompositionPlacement]) -> Optional[CompositionPlacement]:
        for item in items:
            if item.placement_kind in node_kinds:
                return item
            if _long_distance_anchor(item, candidates) is not None:
                return item
        return None

    previous = _node(list(reversed(day.placements[:index])))
    following = _node(list(day.placements[index + 1 :]))
    morning, evening = day_lodging_boundaries(day, composition, candidates)
    previous = previous or morning
    following = following or evening
    if previous is None or following is None:
        raise ItineraryCompositionError(
            f"day {day.day_id} authored connector needs a stop on both sides"
        )
    route = placement.authored_route

    from_endpoint = _chain_endpoint(previous, candidates, leaving=True)
    to_endpoint = _chain_endpoint(following, candidates, leaving=False)
    leg_id = _stable_id(
        "transport",
        placement.connector_gap_id
        or (
            placement_occurrence_key(day.day_id, previous),
            placement_occurrence_key(day.day_id, following),
        ),
        route.mode,
    )
    return TransportLeg(
        transport_leg_id=leg_id,
        transport_class=route.transport_class,
        selected_mode=TransportMode(route.mode),
        from_endpoint=from_endpoint,
        to_endpoint=to_endpoint,
        duration_minutes=route.duration_minutes,
        transfer_count=0,
        segments=[
            TransportSegment(
                segment_id=_stable_id("segment", leg_id),
                mode=TransportMode(route.mode),
                from_endpoint=from_endpoint,
                to_endpoint=to_endpoint,
                duration_minutes=route.duration_minutes,
            )
        ],
        booking_status="not_required",
        route_status="ready",
        lineage=_authored_lineage(),
    )


def _reference_service_notes(
    reference_services: list[ProviderReferenceService],
    *,
    transport_legs: list[TransportLeg],
    day_plans: list[DayPlanV2],
) -> list[str]:

    if not reference_services:
        return []
    long_distance_ids = {
        leg.transport_leg_id
        for leg in transport_legs
        if leg.transport_class == "long_distance"
    }
    dates_with_long_distance = {
        day.date
        for day in day_plans
        if any(
            entry.entity_type == EntityType.TRANSPORT_LEG
            and entry.entity_id in long_distance_ids
            for entry in day.timeline
        )
    }
    return [
        reference_service_note(service)
        for service in reference_services
        if service.requested_date not in dates_with_long_distance
    ]


def materialize_trip_workspace(
    *,
    run_id: str,
    workspace_revision: int,
    composition: ItineraryCompositionDraft,
    catalog: RecommendationCatalog,
    intent_contract_snapshot: IntentContractSnapshot,
    candidate_selection_plan: CandidateSelectionPlan,
    composition_mutations: list[CompositionMutation],
    user_input_anchors: Optional[list[UserInputAnchor]] = None,
    reference_services: Optional[list[ProviderReferenceService]] = None,
    required_candidate_kinds: Optional[set[str]] = None,
    required_long_distance_legs: Optional[list["ProviderRouteLegScope"]] = None,
    required_leg_scope_ids: Optional[dict[str, str]] = None,
) -> TripWorkspaceV2:
    candidates = _passed_candidates(catalog)
    used_ids = {
        placement.candidate_id
        for day in composition.days
        for placement in day.placements
        if placement.candidate_id
    } | set(composition.lodging_candidate_ids)
    missing = used_ids - set(candidates)
    if missing:
        raise ItineraryCompositionError(
            f"composition references candidates that did not pass admission: {sorted(missing)}"
        )
    validate_itinerary_transport_topology(
        composition,
        catalog,
        required_candidate_kinds=required_candidate_kinds,
        required_long_distance_legs=required_long_distance_legs,
        required_leg_scope_ids=required_leg_scope_ids,
    )

    visits: list[VisitStop] = []
    dining: list[DiningStop] = []
    lodging: list[LodgingStay] = []
    transport: list[TransportLeg] = []
    day_plans: list[DayPlanV2] = []
    composition_day_dates = {day.date for day in composition.days}
    deferred_transport_projections: dict[date, list[TimelineEntryRef]] = {}
    slots: list[SelectionSlot] = []
    materialized_long_distance: set[str] = set()
    destination_names = _controlled_destination_names(user_input_anchors)
    placed_visit_candidate_ids = {
        placement.candidate_id
        for day in composition.days
        for placement in day.placements
        if placement.candidate_id and placement.placement_kind == "visit"
    }
    for day in composition.days:
        timeline: list[TimelineEntryRef] = []
        day_visit_start = len(visits)
        day_dining_start = len(dining)
        day_transport_start = len(transport)
        for placement_index, placement in enumerate(day.placements):
            if is_authored_placement(placement):
                if placement.placement_kind == "transport":
                    leg = _authored_transport_leg(
                        day=day,
                        index=placement_index,
                        candidates=candidates,
                        composition=composition,
                    )
                    transport.append(leg)
                    timeline.append(
                        TimelineEntryRef(
                            entry_id=_stable_id("entry", leg.transport_leg_id),
                            entity_type=EntityType.TRANSPORT_LEG,
                            entity_id=leg.transport_leg_id,
                        )
                    )
                    continue
                authored = _located_authored_place(placement)
                if placement.placement_kind == "visit":
                    item_id = _stable_id(
                        "visit", placement_occurrence_key(day.day_id, placement)
                    )
                    visits.append(
                        VisitStop(
                            item_id=item_id,
                            day_id=day.day_id,
                            place_id=authored.resolved_place_id,
                            name=authored.name,
                            address=authored.resolved_address or authored.address,
                            latitude=authored.resolved_latitude,
                            longitude=authored.resolved_longitude,
                            planned_start=placement.planned_start,
                            planned_end=placement.planned_end,
                            duration_minutes=placement.duration_minutes,
                            selection_reason=authored.selection_reason,
                            lineage=_authored_lineage(),
                            visit_type=authored.visit_type,
                            visit_highlights=list(authored.highlights),
                        )
                    )
                    timeline.append(
                        TimelineEntryRef(
                            entry_id=_stable_id("entry", item_id),
                            entity_type=EntityType.VISIT_STOP,
                            entity_id=item_id,
                        )
                    )
                else:
                    item_id = _stable_id(
                        "dining",
                        placement_occurrence_key(day.day_id, placement),
                    )
                    dining.append(
                        DiningStop(
                            item_id=item_id,
                            day_id=day.day_id,
                            place_id=authored.resolved_place_id,
                            name=authored.name,
                            address=authored.resolved_address or authored.address,
                            latitude=authored.resolved_latitude,
                            longitude=authored.resolved_longitude,
                            planned_start=placement.planned_start,
                            planned_end=placement.planned_end,
                            duration_minutes=placement.duration_minutes,
                            selection_reason=authored.selection_reason,
                            lineage=_authored_lineage(),
                            meal_type=placement.meal_type,
                            cuisine_types=list(authored.cuisine_types),
                            recommended_dishes=list(authored.recommended_dishes),
                        )
                    )
                    timeline.append(
                        TimelineEntryRef(
                            entry_id=_stable_id("entry", item_id),
                            entity_type=EntityType.DINING_STOP,
                            entity_id=item_id,
                        )
                    )
                continue
            candidate = candidates[placement.candidate_id]
            if placement.placement_kind == "visit":
                if not isinstance(candidate, VisitCandidate):
                    raise ItineraryCompositionError(
                        "visit placement references another candidate kind"
                    )
                item_id = _stable_id(
                    "visit", placement_occurrence_key(day.day_id, placement)
                )
                visit_position = sum(
                    item.placement_kind == "visit"
                    for item in day.placements[:placement_index]
                )
                slot_id = _stable_id("slot_visit", day.day_id, visit_position)
                eligible = [
                    item
                    for item in candidates.values()
                    if isinstance(item, VisitCandidate)
                    and item.destination_id == day.destination_id
                    and item.candidate_id not in placed_visit_candidate_ids
                ]
                slots.append(
                    _slot(
                        selected=candidate,
                        eligible=eligible,
                        slot_id=slot_id,
                        target_entity_id=item_id,
                        slot_type="visit",
                        context={
                            "day_id": day.day_id,
                            "destination_id": day.destination_id,
                            "visit_type": candidate.visit_type,
                        },
                    )
                )
                visits.append(
                    VisitStop(
                        item_id=item_id,
                        day_id=day.day_id,
                        place_id=candidate.place_id,
                        name=candidate.name,
                        address=candidate.address,
                        planned_start=placement.planned_start,
                        planned_end=placement.planned_end,
                        duration_minutes=placement.duration_minutes,
                        estimated_cost_cny=candidate.estimated_cost_cny,
                        selection_reason=placement.selection_reason
                        or candidate.selection_reasons[0],
                        lineage=_lineage(candidate, slot_id),
                        visit_type=candidate.visit_type,
                        opening_window=candidate.opening_window,
                        reservation_required=candidate.reservation_required,
                        visit_highlights=candidate.highlights,
                    )
                )
                timeline.append(
                    TimelineEntryRef(
                        entry_id=_stable_id("entry", item_id),
                        entity_type=EntityType.VISIT_STOP,
                        entity_id=item_id,
                    )
                )
            elif placement.placement_kind == "dining":
                if (
                    not isinstance(candidate, DiningCandidate)
                    or placement.meal_type not in candidate.meal_types
                ):
                    raise ItineraryCompositionError(
                        "dining placement does not match candidate meal domain"
                    )
                item_id = _stable_id(
                    "dining", placement_occurrence_key(day.day_id, placement)
                )
                slot_id = _stable_id(
                    "slot_dining", placement_occurrence_key(day.day_id, placement)
                )
                eligible = [
                    item
                    for item in candidates.values()
                    if isinstance(item, DiningCandidate)
                    and item.destination_id == day.destination_id
                    and placement.meal_type in item.meal_types
                ]
                slots.append(
                    _slot(
                        selected=candidate,
                        eligible=eligible,
                        slot_id=slot_id,
                        target_entity_id=item_id,
                        slot_type="dining",
                        context={
                            "day_id": day.day_id,
                            "meal_type": placement.meal_type,
                            "destination_id": day.destination_id,
                        },
                    )
                )
                dining.append(
                    DiningStop(
                        item_id=item_id,
                        day_id=day.day_id,
                        place_id=candidate.place_id,
                        name=candidate.branch_name,
                        address=candidate.address,
                        planned_start=placement.planned_start,
                        planned_end=placement.planned_end,
                        duration_minutes=placement.duration_minutes,
                        estimated_cost_cny=candidate.average_spend_cny,
                        selection_reason=placement.selection_reason
                        or candidate.selection_reasons[0],
                        lineage=_lineage(candidate, slot_id),
                        meal_type=placement.meal_type,
                        cuisine_types=candidate.cuisine_types,
                        average_spend_cny=candidate.average_spend_cny,
                        recommended_dishes=candidate.recommended_dishes,
                        reservation_required=candidate.reservation_required,
                        opening_window=candidate.opening_window,
                    )
                )
                timeline.append(
                    TimelineEntryRef(
                        entry_id=_stable_id("entry", item_id),
                        entity_type=EntityType.DINING_STOP,
                        entity_id=item_id,
                    )
                )
            else:
                if not isinstance(candidate, TransportCandidate):
                    raise ItineraryCompositionError(
                        "transport placement references another candidate kind"
                    )
                if candidate.transport_class == "long_distance":
                    if candidate.candidate_id in materialized_long_distance:
                        continue
                    materialized_long_distance.add(candidate.candidate_id)
                leg_id = (
                    _stable_id("transport", candidate.candidate_id)
                    if candidate.transport_class == "long_distance"
                    else _stable_id(
                        "transport", placement_occurrence_key(day.day_id, placement)
                    )
                )
                transport.append(
                    TransportLeg(
                        transport_leg_id=leg_id,
                        transport_class=candidate.transport_class,
                        selected_mode=candidate.selected_mode,
                        from_endpoint=candidate.from_endpoint,
                        to_endpoint=candidate.to_endpoint,
                        departure_at=candidate.departure_at,
                        arrival_at=candidate.arrival_at,
                        duration_minutes=candidate.duration_minutes,
                        distance_meters=candidate.distance_meters,
                        total_cost_cny=candidate.total_cost_cny,
                        transfer_count=count_service_transfers(candidate.segments),
                        segments=candidate.segments,
                        booking_status=candidate.booking_status,
                        route_status="ready",
                        lineage=_lineage(candidate),
                    )
                )
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
                projection_shape = classify_transport_projection_shape(
                    transport_class=candidate.transport_class,
                    departure_at=candidate.departure_at,
                    arrival_at=candidate.arrival_at,
                    itinerary_dates=composition_day_dates,
                )
                if projection_shape == "cross_night_split":
                    current_role = (
                        "departure" if day.date == departure_date else "arrival"
                    )
                    other_date = (
                        arrival_date if current_role == "departure" else departure_date
                    )
                    other_role = (
                        "arrival" if current_role == "departure" else "departure"
                    )
                    timeline.append(
                        TimelineEntryRef(
                            entry_id=_stable_id("entry", leg_id, current_role),
                            entity_type=EntityType.TRANSPORT_LEG,
                            entity_id=leg_id,
                            projection_role=current_role,
                        )
                    )
                    deferred_transport_projections.setdefault(other_date, []).append(
                        TimelineEntryRef(
                            entry_id=_stable_id("entry", leg_id, other_role),
                            entity_type=EntityType.TRANSPORT_LEG,
                            entity_id=leg_id,
                            projection_role=other_role,
                        )
                    )
                elif projection_shape == "outside_itinerary":
                    raise ItineraryCompositionError(
                        "long-distance transport service dates fall outside the itinerary"
                    )
                else:
                    timeline.append(
                        TimelineEntryRef(
                            entry_id=_stable_id("entry", leg_id),
                            entity_type=EntityType.TRANSPORT_LEG,
                            entity_id=leg_id,
                        )
                    )
        day_plans.append(
            DayPlanV2(
                day_id=day.day_id,
                day=day.day,
                date=day.date,
                destination_id=day.destination_id,
                theme=derive_day_theme(
                    destination_name=destination_names.get(day.destination_id),
                    visits=visits[day_visit_start:],
                    dining=dining[day_dining_start:],
                    long_distance_legs=[
                        leg
                        for leg in transport[day_transport_start:]
                        if leg.transport_class == "long_distance"
                    ],
                ),
                timeline=timeline,
                time_structure=day.time_structure,
            )
        )

    if deferred_transport_projections:
        day_by_date = {day.date: day for day in day_plans}
        missing_dates = set(deferred_transport_projections) - set(day_by_date)
        if missing_dates:
            raise ItineraryCompositionError(
                f"cross-night transport projection dates are missing: {sorted(missing_dates)}"
            )
        day_plans = [
            day.model_copy(
                update={
                    "timeline": [
                        *[
                            ref
                            for ref in deferred_transport_projections.get(day.date, [])
                            if ref.projection_role == "arrival"
                        ],
                        *day.timeline,
                        *[
                            ref
                            for ref in deferred_transport_projections.get(day.date, [])
                            if ref.projection_role == "departure"
                        ],
                    ]
                }
            )
            for day in day_plans
        ]

    placed_stay_ids: set[str] = set()
    lodging_projections: dict[date, list[TimelineEntryRef]] = {}
    for candidate_id in composition.lodging_candidate_ids:
        candidate = candidates[candidate_id]
        if not isinstance(candidate, LodgingCandidate):
            raise ItineraryCompositionError(
                "lodging choice references another candidate kind"
            )
        window = _destination_stay_window(
            composition,
            candidate.destination_id,
            candidate.check_in_date,
            candidate.check_out_date,
        )
        if window is None:
            continue
        check_in_date, check_out_date = window
        nights = (check_out_date - check_in_date).days
        stay_id = _stable_id(
            "lodging", candidate.destination_id, check_in_date, check_out_date
        )
        if stay_id in placed_stay_ids:
            continue
        placed_stay_ids.add(stay_id)
        slot_id = _stable_id(
            "slot_lodging", candidate.destination_id, check_in_date, check_out_date
        )
        eligible = [
            item
            for item in candidates.values()
            if isinstance(item, LodgingCandidate)
            and item.destination_id == candidate.destination_id
            and _destination_stay_window(
                composition,
                item.destination_id,
                item.check_in_date,
                item.check_out_date,
            )
            == window
        ]
        slots.append(
            _slot(
                selected=candidate,
                eligible=eligible,
                slot_id=slot_id,
                target_entity_id=stay_id,
                slot_type="lodging",
                context={
                    "destination_id": candidate.destination_id,
                    "check_in_date": check_in_date.isoformat(),
                    "check_out_date": check_out_date.isoformat(),
                },
            )
        )
        lodging.append(
            LodgingStay(
                stay_id=stay_id,
                place_id=candidate.place_id,
                name=candidate.property_name,
                check_in_date=check_in_date,
                check_out_date=check_out_date,
                nights=nights,
                room_type=candidate.room_type,
                nightly_price_cny=candidate.nightly_price_cny,
                total_price_cny=candidate.total_price_cny,
                price_kind=candidate.price_kind,
                availability_status=candidate.availability_status,
                address=candidate.address,
                selection_reason=candidate.selection_reasons[0],
                lineage=_lineage(candidate, slot_id),
            )
        )
        for role, projection_date in (
            ("check_in", check_in_date),
            ("check_out", check_out_date),
        ):
            if projection_date not in composition_day_dates:
                continue
            lodging_projections.setdefault(projection_date, []).append(
                TimelineEntryRef(
                    entry_id=_stable_id("entry", stay_id, role),
                    entity_type=EntityType.LODGING_STAY,
                    entity_id=stay_id,
                    projection_role=role,
                )
            )

    if lodging_projections:
        day_plans = [
            day.model_copy(
                update={
                    "timeline": [
                        *[
                            ref
                            for ref in lodging_projections.get(day.date, [])
                            if ref.projection_role == "check_out"
                        ],
                        *day.timeline,
                        *[
                            ref
                            for ref in lodging_projections.get(day.date, [])
                            if ref.projection_role == "check_in"
                        ],
                    ]
                }
            )
            for day in day_plans
        ]

    transport_slots, transport = _transport_slots(transport, candidates)
    slots.extend(transport_slots)
    itinerary = StructuredItineraryV2(
        itinerary_id=composition.itinerary_id,
        title=composition.title,
        destination_ids=list(
            dict.fromkeys(day.destination_id for day in composition.days)
        ),
        duration_days=composition.duration_days,
        day_plans=day_plans,
        visit_stops=visits,
        dining_stops=dining,
        lodging_stays=lodging,
        transport_legs=transport,
        cost_summary=build_cost_coverage_summary(
            itinerary_price_components(
                visit_stops=visits,
                dining_stops=dining,
                lodging_stays=lodging,
                transport_legs=transport,
            ),
            budget_cap_cny=_total_budget_cap_cny(user_input_anchors),
        ),
        highlights=derive_trip_highlights(
            visits=visits,
            dining=dining,
            lodging=lodging,
            transport_legs=transport,
        ),
        important_notes=_reference_service_notes(
            reference_services or [], transport_legs=transport, day_plans=day_plans
        ),
    )
    admissions = list(catalog.admission_results)
    admission_index = catalog.admission_index()
    for slot in slots:
        for option in slot.options:
            key = (option.candidate_id, slot.selection_slot_id)
            if key in admission_index:
                continue
            base = admission_index.get((option.candidate_id, None)) or next(
                (
                    item
                    for item in catalog.admission_results
                    if item.candidate_id == option.candidate_id
                    and item.status == "passed"
                ),
                None,
            )
            if base is None or base.status != "passed":
                raise ItineraryCompositionError(
                    "selection slot option lacks a passed candidate admission"
                )
            scoped = base.model_copy(
                update={"selection_slot_id": slot.selection_slot_id}
            )
            admissions.append(scoped)
            admission_index[key] = scoped
    catalog = catalog.model_copy(update={"admission_results": admissions})
    return TripWorkspaceV2(
        run_id=run_id,
        generation_id=catalog.generation_id,
        workspace_revision=workspace_revision,
        itinerary=itinerary,
        recommendation_catalog=catalog,
        intent_contract_snapshot=intent_contract_snapshot,
        composition_mutations=composition_mutations,
        candidate_selection_plan=candidate_selection_plan,
        user_input_anchors=user_input_anchors or [],
        selection_slots=slots,
    )


def _restore_full_catalog(
    workspace: TripWorkspaceV2,
    full_catalog: RecommendationCatalog | None,
) -> TripWorkspaceV2:
    if full_catalog is None:
        return workspace
    admissions = {
        (result.candidate_id, result.selection_slot_id): result
        for result in full_catalog.admission_results
    }
    admissions.update(
        {
            (result.candidate_id, result.selection_slot_id): result
            for result in workspace.recommendation_catalog.admission_results
            if result.selection_slot_id is not None
        }
    )
    restored_catalog = full_catalog.model_copy(
        update={"admission_results": list(admissions.values())}
    )
    return workspace.model_copy(update={"recommendation_catalog": restored_catalog})
