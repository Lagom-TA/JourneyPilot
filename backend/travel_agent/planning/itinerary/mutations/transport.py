"""Planning itinerary mutations transport."""

from __future__ import annotations

from travel_agent.planning.itinerary.models import TransportLeg
from travel_agent.planning.itinerary.mutations.contracts import (
    DeleteTransportLegMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import SetTransportModeMutation
from travel_agent.planning.itinerary.mutations.contracts import (
    UpdateTransportModePreferenceMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import (
    WorkspaceV2MutationApplication,
)
from travel_agent.planning.itinerary.mutations.contracts import WorkspaceV2MutationError
from travel_agent.planning.itinerary.mutations.results import _itinerary_result
from travel_agent.planning.itinerary.mutations.results import _snapshot_result
from travel_agent.planning.references import EntityLineage
from travel_agent.planning.references import EntityType
from travel_agent.planning.research.candidates import TransportCandidate
from travel_agent.planning.transport import TransportModePreference
from travel_agent.planning.transport_semantics import count_service_transfers
from travel_agent.planning.workspace import TripWorkspaceV2


def _transport_from_candidate(
    current: TransportLeg,
    candidate: TransportCandidate,
) -> TransportLeg:
    return TransportLeg(
        transport_leg_id=current.transport_leg_id,
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
        mode_preference=current.mode_preference,
        lineage=EntityLineage(
            research_packet_id=candidate.research_packet_id,
            candidate_id=candidate.candidate_id,
            fact_assertion_ids=candidate.fact_assertion_ids,
            source_record_ids=candidate.source_record_ids,
            planning_decision_ids=candidate.planning_decision_ids,
            weather_impact_ids=candidate.weather_impact_ids,
            personalization_influence_ids=candidate.personalization_influence_ids,
        ),
    )


def _check_transport_replacement(
    current: TransportLeg,
    candidate: TransportCandidate,
) -> None:
    """Refuse a transport candidate that cannot lawfully stand in for this leg.

    The composition asks the same questions when it decides which candidates to
    *offer* (``planning.itinerary.selection._transport_alternatives``), so a slot
    normally never presents an option this function would then reject.  The check
    still has to run at apply time: a slot is built once, and a mode preference
    set afterwards can make an already-offered option unusable.
    """

    preference = current.mode_preference
    if (
        preference.locked_mode is not None
        and candidate.selected_mode != preference.locked_mode
    ):
        raise WorkspaceV2MutationError(
            "transport_mode_locked",
            "Replacement candidate conflicts with the locked transport mode",
        )
    if candidate.selected_mode in preference.excluded_modes:
        raise WorkspaceV2MutationError(
            "transport_mode_excluded",
            "Replacement candidate uses an excluded transport mode",
        )
    same_local_connector = (
        current.from_endpoint.place_id is not None
        and current.to_endpoint.place_id is not None
        and candidate.from_endpoint.place_id == current.from_endpoint.place_id
        and candidate.to_endpoint.place_id == current.to_endpoint.place_id
    )
    if current.transport_class == "long_distance":
        if candidate.transport_class != "long_distance":
            raise WorkspaceV2MutationError(
                "transport_replacement_context_mismatch",
                "Long-distance transport can only be replaced by another long-distance option",
            )
    elif (
        candidate.transport_class not in {"public_transit", "flexible"}
        or not same_local_connector
    ):
        raise WorkspaceV2MutationError(
            "transport_replacement_context_mismatch",
            "Local transport replacement must connect the same ordered endpoints",
        )


def _check_preference_leaves_a_way_back(
    workspace: TripWorkspaceV2,
    current: TransportLeg,
    preference: TransportModePreference,
) -> None:
    """Refuse a mode preference that would strand this leg with no route.

    The invariant this defends: **after any accepted preference change, the leg
    still has at least one entrance that can put it back to ``ready``.**  That
    entrance is always the same one — ``select_option`` on the leg's slot — and
    ``_check_transport_replacement`` decides which of the slot's options it will
    accept.  Lock a mode the catalog cannot serve, or exclude every mode it can,
    and every option is refused: the leg's ``route_status`` sticks at
    ``pending`` with no duration and no cost, and nothing short of undoing the
    preference reaches it again.

    Checked here rather than at the two call sites because both of them set the
    same field, and the previous split — ``set_transport_mode`` guarding nothing
    and ``update_transport_mode_preference`` guarding nothing either — is how the
    hole stayed open through two rounds.

    A leg with no slot is exempt, and deliberately so: it has no options to
    refuse, so the preference cannot be what strands it.  Those are the
    planner-authored connectors, which never had a selection entrance to lose.
    """

    slot = next(
        (
            item
            for item in workspace.selection_slots
            if item.slot_type == "transport"
            and item.target_entity_id == current.transport_leg_id
        ),
        None,
    )
    if slot is None:
        return
    probe = current.model_copy(update={"mode_preference": preference})
    candidates = workspace.recommendation_catalog.candidate_index()
    admissions = workspace.recommendation_catalog.admission_index()
    for option in slot.options:
        candidate = candidates.get(option.candidate_id)
        admission = admissions.get((option.candidate_id, slot.selection_slot_id))
        if (
            not isinstance(candidate, TransportCandidate)
            or admission is None
            or admission.status != "passed"
        ):
            continue
        try:
            _check_transport_replacement(probe, candidate)
        except WorkspaceV2MutationError:
            continue
        return
    raise WorkspaceV2MutationError(
        "transport_preference_strands_leg",
        "No admitted option for this leg survives the requested mode preference",
    )


def apply_delete_transport_leg(
    workspace: TripWorkspaceV2, mutation: DeleteTransportLegMutation
) -> WorkspaceV2MutationApplication:
    itinerary = workspace.itinerary
    current = next(
        (
            item
            for item in itinerary.transport_legs
            if item.transport_leg_id == mutation.transport_leg_id
        ),
        None,
    )
    if current is None:
        raise WorkspaceV2MutationError(
            "transport_leg_not_found", "Transport leg does not exist"
        )
    day_plans = [
        day.model_copy(
            update={
                "timeline": [
                    ref
                    for ref in day.timeline
                    if not (
                        ref.entity_type == EntityType.TRANSPORT_LEG
                        and ref.entity_id == mutation.transport_leg_id
                    )
                ]
            }
        )
        for day in itinerary.day_plans
    ]
    next_itinerary = itinerary.model_copy(
        update={
            "day_plans": day_plans,
            "transport_legs": [
                item
                for item in itinerary.transport_legs
                if item.transport_leg_id != mutation.transport_leg_id
            ],
        }
    )

    return _snapshot_result(
        workspace,
        workspace.model_copy(
            update={
                "selection_slots": [
                    item
                    for item in workspace.selection_slots
                    if item.target_entity_id != mutation.transport_leg_id
                ],
                "itinerary": next_itinerary,
            }
        ),
        "删除交通安排",
    )


def apply_update_transport_mode_preference(
    workspace: TripWorkspaceV2, mutation: UpdateTransportModePreferenceMutation
) -> WorkspaceV2MutationApplication:
    itinerary = workspace.itinerary
    current = next(
        (
            item
            for item in itinerary.transport_legs
            if item.transport_leg_id == mutation.transport_leg_id
        ),
        None,
    )
    if current is None:
        raise WorkspaceV2MutationError(
            "transport_leg_not_found", "Transport leg does not exist"
        )
    values = {
        name: getattr(mutation, name)
        for name in ("locked_mode", "excluded_modes")
        if name in mutation.model_fields_set
    }
    preference = current.mode_preference.model_copy(update=values)
    preference = type(current.mode_preference).model_validate(
        preference.model_dump(mode="json")
    )
    if preference == current.mode_preference:
        return WorkspaceV2MutationApplication(workspace=workspace, changed=False)
    _check_preference_leaves_a_way_back(workspace, current, preference)
    updated = current.model_copy(update={"mode_preference": preference})
    return _itinerary_result(
        workspace,
        itinerary.model_copy(
            update={
                "transport_legs": [
                    updated
                    if item.transport_leg_id == current.transport_leg_id
                    else item
                    for item in itinerary.transport_legs
                ]
            }
        ),
        "更新交通偏好",
    )


def apply_set_transport_mode(
    workspace: TripWorkspaceV2, mutation: SetTransportModeMutation
) -> WorkspaceV2MutationApplication:
    itinerary = workspace.itinerary
    current = next(
        (
            item
            for item in itinerary.transport_legs
            if item.transport_leg_id == mutation.transport_leg_id
        ),
        None,
    )
    if current is None:
        raise WorkspaceV2MutationError(
            "transport_leg_not_found", "Transport leg does not exist"
        )
    if current.transport_class == "long_distance":
        raise WorkspaceV2MutationError(
            "long_distance_requires_option",
            "Long-distance transport requires explicit option replacement",
        )
    if mutation.selected_mode in current.mode_preference.excluded_modes:
        raise WorkspaceV2MutationError(
            "transport_mode_excluded",
            "Selected mode is excluded by user preference",
        )
    preference = current.mode_preference.model_copy(
        update={"locked_mode": mutation.selected_mode if mutation.lock_mode else None}
    )
    if preference != current.mode_preference:
        _check_preference_leaves_a_way_back(workspace, current, preference)
    if current.selected_mode == mutation.selected_mode:
        if preference == current.mode_preference:
            return WorkspaceV2MutationApplication(workspace=workspace, changed=False)
        updated = current.model_copy(update={"mode_preference": preference})
        return _itinerary_result(
            workspace,
            itinerary.model_copy(
                update={
                    "transport_legs": [
                        updated
                        if item.transport_leg_id == current.transport_leg_id
                        else item
                        for item in itinerary.transport_legs
                    ]
                }
            ),
            "更新交通偏好",
        )
    updated = current.model_copy(
        update={
            "selected_mode": mutation.selected_mode,
            "mode_preference": preference,
            "segments": [],
            "transfer_count": 0,
            "route_status": "pending",
            "duration_minutes": None,
            "distance_meters": None,
            "total_cost_cny": None,
        }
    )
    return _itinerary_result(
        workspace,
        itinerary.model_copy(
            update={
                "transport_legs": [
                    updated
                    if item.transport_leg_id == current.transport_leg_id
                    else item
                    for item in itinerary.transport_legs
                ]
            }
        ),
        "切换交通方式",
    )
