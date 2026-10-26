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
    """拒绝不能合法替代当前行程段的交通候选。

    组合阶段在决定提供哪些候选时
    （``planning.itinerary.selection._transport_alternatives``）会做同样的判断，
    因此槽位通常不会给出会被本函数拒绝的选项。应用时仍须校验：槽位只构建一次，
    之后设置的交通方式偏好可能让已提供的选项不可用。
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
    """拒绝会让该行程段没有可用替代方案的交通偏好。

    约束：偏好变更被接受后，该行程段的 selection slot 中必须仍至少有一个候选
    能通过 ``_check_transport_replacement`` 的替换校验；否则 ``select_option``
    无法重新选择，行程段的 ``route_status`` 会一直停在 ``pending``。校验放在
    这里而不是两个调用点，因为两者写同一个字段。

    没有 slot 的行程段不受影响：它没有可拒绝的选项，偏好不会使其无法选择。
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
    for option in slot.options:
        candidate = candidates.get(option.candidate_id)
        if not isinstance(candidate, TransportCandidate):
            continue
        try:
            _check_transport_replacement(probe, candidate)
        except WorkspaceV2MutationError:
            continue
        return
    raise WorkspaceV2MutationError(
        "transport_preference_strands_leg",
        "候选目录中没有该行程段在新偏好下仍可替换的方案",
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
