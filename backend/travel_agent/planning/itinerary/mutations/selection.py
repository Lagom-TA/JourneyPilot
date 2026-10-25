"""Planning itinerary mutations selection."""

from __future__ import annotations

from datetime import timedelta
from travel_agent.planning.itinerary.models import DiningStop
from travel_agent.planning.itinerary.models import LodgingStay
from travel_agent.planning.itinerary.models import TransportLeg
from travel_agent.planning.itinerary.models import VisitStop
from travel_agent.planning.itinerary.mutations.contracts import (
    DeleteLodgingStayMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import SelectOptionMutation
from travel_agent.planning.itinerary.mutations.contracts import SelectableEntity
from travel_agent.planning.itinerary.mutations.contracts import SelectionInversePatch
from travel_agent.planning.itinerary.mutations.contracts import (
    WorkspaceV2MutationApplication,
)
from travel_agent.planning.itinerary.mutations.contracts import WorkspaceV2MutationError
from travel_agent.planning.itinerary.mutations.results import _snapshot_result
from travel_agent.planning.itinerary.mutations.timeline import _drop_stale_day_notes
from travel_agent.planning.itinerary.mutations.timeline import (
    _invalidate_changed_connectors,
)
from travel_agent.planning.itinerary.mutations.timeline import (
    _validate_changed_stop_windows,
)
from travel_agent.planning.itinerary.mutations.transport import (
    _check_transport_replacement,
)
from travel_agent.planning.itinerary.mutations.transport import (
    _transport_from_candidate,
)
from travel_agent.planning.itinerary.options import SelectionOption
from travel_agent.planning.itinerary.options import SelectionSlot
from travel_agent.planning.references import EntityLineage
from travel_agent.planning.references import EntityType
from travel_agent.planning.research.candidates import DiningCandidate
from travel_agent.planning.research.candidates import LodgingCandidate
from travel_agent.planning.research.candidates import TransportCandidate
from travel_agent.planning.research.candidates import VisitCandidate
from travel_agent.planning.research.option_availability import (
    candidate_option_availability,
)
from travel_agent.planning.workspace import TripWorkspaceV2


def _slot(workspace: TripWorkspaceV2, selection_slot_id: str) -> SelectionSlot:
    for slot in workspace.selection_slots:
        if slot.selection_slot_id == selection_slot_id:
            return slot
    raise WorkspaceV2MutationError(
        "selection_slot_not_found", "SelectionSlot does not exist"
    )


def _option(slot: SelectionSlot, option_id: str) -> SelectionOption:
    for option in slot.options:
        if option.option_id == option_id:
            return option
    raise WorkspaceV2MutationError(
        "selection_option_not_found", "Option does not belong to SelectionSlot"
    )


def _lineage(
    candidate: DiningCandidate | LodgingCandidate,
    slot: SelectionSlot,
    option: SelectionOption,
) -> EntityLineage:
    return EntityLineage(
        research_packet_id=candidate.research_packet_id,
        candidate_id=candidate.candidate_id,
        selection_slot_id=slot.selection_slot_id,
        fact_assertion_ids=option.fact_assertion_ids,
        source_record_ids=option.source_record_ids,
        planning_decision_ids=candidate.planning_decision_ids,
        weather_impact_ids=candidate.weather_impact_ids,
        personalization_influence_ids=option.personalization_influence_ids,
    )


def _selection_reason(option: SelectionOption) -> str:
    return "；".join(
        reason.strip() for reason in option.selection_reasons if reason.strip()
    )


def _replace_dining(
    workspace: TripWorkspaceV2,
    slot: SelectionSlot,
    option: SelectionOption,
    candidate: DiningCandidate,
) -> tuple[DiningStop, DiningStop]:
    current = next(
        (
            item
            for item in workspace.itinerary.dining_stops
            if item.item_id == slot.target_entity_id
        ),
        None,
    )
    if current is None:
        raise WorkspaceV2MutationError(
            "canonical_entity_not_found", "DiningStop target does not exist"
        )
    if current.meal_type not in candidate.meal_types:
        raise WorkspaceV2MutationError(
            "meal_context_mismatch", "Candidate does not serve the slot meal"
        )
    return current, DiningStop(
        item_id=current.item_id,
        day_id=current.day_id,
        place_id=candidate.place_id,
        name=candidate.branch_name,
        address=candidate.address,
        planned_start=current.planned_start,
        planned_end=current.planned_end,
        duration_minutes=current.duration_minutes,
        estimated_cost_cny=candidate.average_spend_cny,
        selection_reason=_selection_reason(option),
        lineage=_lineage(candidate, slot, option),
        meal_type=current.meal_type,
        cuisine_types=candidate.cuisine_types,
        average_spend_cny=candidate.average_spend_cny,
        recommended_dishes=candidate.recommended_dishes,
        reservation_required=candidate.reservation_required,
        opening_window=candidate.opening_window,
    )


def _replace_lodging(
    workspace: TripWorkspaceV2,
    slot: SelectionSlot,
    option: SelectionOption,
    candidate: LodgingCandidate,
) -> tuple[LodgingStay, LodgingStay]:
    current = next(
        (
            item
            for item in workspace.itinerary.lodging_stays
            if item.stay_id == slot.target_entity_id
        ),
        None,
    )
    if current is None:
        raise WorkspaceV2MutationError(
            "canonical_entity_not_found", "LodgingStay target does not exist"
        )
    if (
        candidate.check_in_date != current.check_in_date
        or candidate.check_out_date != current.check_out_date
    ):
        raise WorkspaceV2MutationError(
            "stay_context_mismatch", "Candidate does not cover the complete stay"
        )
    return current, LodgingStay(
        stay_id=current.stay_id,
        place_id=candidate.place_id,
        name=candidate.property_name,
        check_in_date=candidate.check_in_date,
        check_out_date=candidate.check_out_date,
        check_in_time=current.check_in_time,
        check_out_time=current.check_out_time,
        nights=candidate.nights,
        room_type=candidate.room_type,
        nightly_price_cny=candidate.nightly_price_cny,
        total_price_cny=candidate.total_price_cny,
        price_kind=candidate.price_kind,
        availability_status=candidate.availability_status,
        address=candidate.address,
        selection_reason=_selection_reason(option),
        lineage=_lineage(candidate, slot, option),
    )


def _replace_visit_stop(
    workspace: TripWorkspaceV2,
    slot: SelectionSlot,
    option: SelectionOption,
    candidate: VisitCandidate,
) -> tuple[VisitStop, VisitStop]:
    """Swap the attraction standing in one plan position.

    The stop keeps its window: a visit slot offers a different place for the same
    hole in the Day, so the schedule the composition solved for stays put and only
    the duration follows the new candidate — the same division dining and lodging
    already make.
    """

    current = next(
        (
            item
            for item in workspace.itinerary.visit_stops
            if item.item_id == slot.target_entity_id
        ),
        None,
    )
    if current is None:
        raise WorkspaceV2MutationError(
            "canonical_entity_not_found", "VisitStop target does not exist"
        )
    planned_end = (
        current.planned_start
        + timedelta(minutes=candidate.recommended_duration_minutes)
        if current.planned_start is not None
        else current.planned_end
    )
    return current, VisitStop(
        item_id=current.item_id,
        day_id=current.day_id,
        place_id=candidate.place_id,
        name=candidate.name,
        address=candidate.address,
        planned_start=current.planned_start,
        planned_end=planned_end,
        duration_minutes=candidate.recommended_duration_minutes,
        estimated_cost_cny=candidate.estimated_cost_cny,
        selection_reason=_selection_reason(option),
        lineage=_lineage(candidate, slot, option),
        visit_type=candidate.visit_type,
        opening_window=candidate.opening_window,
        reservation_required=candidate.reservation_required,
        visit_highlights=candidate.highlights,
    )


def _replace_transport_leg(
    workspace: TripWorkspaceV2,
    slot: SelectionSlot,
    option: SelectionOption,
    candidate: TransportCandidate,
) -> tuple[TransportLeg, TransportLeg]:
    """Bind one journey in the plan to a different admitted route.

    The eligibility rules live in ``_check_transport_replacement`` rather than
    inline, so the offering side (``planning.itinerary.selection``) has one named
    thing to restate.  ``lineage.selection_slot_id`` is carried over from the leg
    the slot points at, because the workspace contract requires a slot's target
    to name it.
    """

    current = next(
        (
            item
            for item in workspace.itinerary.transport_legs
            if item.transport_leg_id == slot.target_entity_id
        ),
        None,
    )
    if current is None:
        raise WorkspaceV2MutationError(
            "canonical_entity_not_found", "TransportLeg target does not exist"
        )
    _check_transport_replacement(current, candidate)
    updated = _transport_from_candidate(current, candidate)
    return current, updated.model_copy(
        update={
            "lineage": updated.lineage.model_copy(
                update={"selection_slot_id": slot.selection_slot_id}
            )
        }
    )


def _selection_label(entity: SelectableEntity) -> str:
    """What the traveller sees this selection called in the undo list.

    A leg has no ``name`` of its own — it is a journey between two places — so it
    is named by the journey rather than crashing on a field only the three place
    entities carry.
    """

    if isinstance(entity, TransportLeg):
        return f"选择{entity.from_endpoint.name} → {entity.to_endpoint.name}"
    return f"选择{entity.name}"


def _selection_is_unrealized(workspace: TripWorkspaceV2, slot: SelectionSlot) -> bool:
    """Whether the itinerary does *not* yet reflect the slot's own selection.

    Re-picking the option a slot already names is normally nothing to do.  A
    transport leg is the exception: a leg can be selected and still hold no route
    — that is exactly the state ``set_transport_mode`` leaves behind, and the
    state a provider outage leaves behind — and re-picking it there means "bind a
    real route for this choice".

    Answering it this way is what makes rebinding reachable from a client at all,
    and it is the whole reason no second identifier is needed for it: the slot's
    ``option_id`` is the only identity this boundary publishes.
    """

    if slot.slot_type != "transport":
        return False
    leg = next(
        (
            item
            for item in workspace.itinerary.transport_legs
            if item.transport_leg_id == slot.target_entity_id
        ),
        None,
    )
    return leg is not None and leg.route_status != "ready"


def _apply_selection(
    workspace: TripWorkspaceV2, mutation: SelectOptionMutation
) -> WorkspaceV2MutationApplication:
    slot = _slot(workspace, mutation.selection_slot_id)
    option = _option(slot, mutation.option_id)
    if slot.selected_option_id == option.option_id and not _selection_is_unrealized(
        workspace, slot
    ):
        return WorkspaceV2MutationApplication(workspace=workspace, changed=False)
    if slot.status not in {"ready", "needs_user_decision"}:
        raise WorkspaceV2MutationError(
            "selection_slot_not_ready", "SelectionSlot is not selectable"
        )
    candidate = workspace.recommendation_catalog.candidate_index().get(
        option.candidate_id
    )
    if candidate is None:
        raise WorkspaceV2MutationError(
            "candidate_not_found", "Selection option has no matching candidate"
        )
    if getattr(candidate, "availability_status", None) == "unavailable":
        raise WorkspaceV2MutationError(
            "candidate_unavailable", "Unavailable candidate cannot be selected"
        )

    if candidate_option_availability(candidate) != option.availability_status:
        raise WorkspaceV2MutationError(
            "availability_mismatch", "Option availability differs from candidate"
        )
    itinerary = workspace.itinerary
    if slot.slot_type == "dining":
        if (
            not isinstance(candidate, DiningCandidate)
            or option.candidate_entity_ref.entity_type != EntityType.DINING_STOP
        ):
            raise WorkspaceV2MutationError(
                "candidate_type_mismatch", "Dining slot requires DiningCandidate"
            )
        previous, updated = _replace_dining(workspace, slot, option, candidate)
        itinerary = itinerary.model_copy(
            update={
                "dining_stops": [
                    updated if item.item_id == previous.item_id else item
                    for item in itinerary.dining_stops
                ],
            }
        )
    elif slot.slot_type == "visit":
        if (
            not isinstance(candidate, VisitCandidate)
            or option.candidate_entity_ref.entity_type != EntityType.VISIT_STOP
        ):
            raise WorkspaceV2MutationError(
                "candidate_type_mismatch", "Visit slot requires VisitCandidate"
            )
        previous, updated = _replace_visit_stop(workspace, slot, option, candidate)
        itinerary = itinerary.model_copy(
            update={
                "visit_stops": [
                    updated if item.item_id == previous.item_id else item
                    for item in itinerary.visit_stops
                ],
            }
        )
    elif slot.slot_type == "transport":
        if (
            not isinstance(candidate, TransportCandidate)
            or option.candidate_entity_ref.entity_type != EntityType.TRANSPORT_LEG
        ):
            raise WorkspaceV2MutationError(
                "candidate_type_mismatch", "Transport slot requires TransportCandidate"
            )
        previous, updated = _replace_transport_leg(workspace, slot, option, candidate)
        itinerary = itinerary.model_copy(
            update={
                "transport_legs": [
                    updated
                    if item.transport_leg_id == previous.transport_leg_id
                    else item
                    for item in itinerary.transport_legs
                ],
            }
        )
    else:
        if (
            not isinstance(candidate, LodgingCandidate)
            or option.candidate_entity_ref.entity_type != EntityType.LODGING_STAY
        ):
            raise WorkspaceV2MutationError(
                "candidate_type_mismatch", "Lodging slot requires LodgingCandidate"
            )
        previous, updated = _replace_lodging(workspace, slot, option, candidate)
        itinerary = itinerary.model_copy(
            update={
                "lodging_stays": [
                    updated if item.stay_id == previous.stay_id else item
                    for item in itinerary.lodging_stays
                ],
            }
        )
    _validate_changed_stop_windows(workspace, itinerary)
    itinerary = _drop_stale_day_notes(
        workspace, _invalidate_changed_connectors(itinerary)
    )
    next_slot = slot.model_copy(
        update={"selected_option_id": option.option_id, "status": "ready"}
    )
    next_workspace = TripWorkspaceV2.model_validate(
        workspace.model_copy(
            update={
                "workspace_revision": workspace.workspace_revision + 1,
                "itinerary": itinerary,
                "selection_slots": [
                    next_slot
                    if item.selection_slot_id == slot.selection_slot_id
                    else item
                    for item in workspace.selection_slots
                ],
            }
        ).model_dump(mode="json")
    )
    return WorkspaceV2MutationApplication(
        workspace=next_workspace,
        changed=True,
        label=_selection_label(updated),
        inverse=SelectionInversePatch(
            selection_slot_id=slot.selection_slot_id,
            applied_option_id=option.option_id,
            applied_workspace_revision=next_workspace.workspace_revision,
            previous_selected_option_id=slot.selected_option_id,
            previous_slot_status=slot.status,
            previous_entity=previous,
        ),
    )


def apply_delete_lodging_stay(
    workspace: TripWorkspaceV2, mutation: DeleteLodgingStayMutation
) -> WorkspaceV2MutationApplication:
    itinerary = workspace.itinerary
    current = next(
        (item for item in itinerary.lodging_stays if item.stay_id == mutation.stay_id),
        None,
    )
    if current is None:
        raise WorkspaceV2MutationError(
            "lodging_stay_not_found", "Lodging stay does not exist"
        )
    day_plans = [
        day.model_copy(
            update={
                "timeline": [
                    ref
                    for ref in day.timeline
                    if not (
                        ref.entity_type == EntityType.LODGING_STAY
                        and ref.entity_id == mutation.stay_id
                    )
                ]
            }
        )
        for day in itinerary.day_plans
    ]
    selection_slots = [
        item
        for item in workspace.selection_slots
        if item.target_entity_id != mutation.stay_id
    ]
    next_itinerary = itinerary.model_copy(
        update={
            "day_plans": day_plans,
            "lodging_stays": [
                item
                for item in itinerary.lodging_stays
                if item.stay_id != mutation.stay_id
            ],
        }
    )
    return _snapshot_result(
        workspace,
        workspace.model_copy(
            update={
                "selection_slots": selection_slots,
                "itinerary": next_itinerary,
            }
        ),
        "删除整段住宿",
    )
