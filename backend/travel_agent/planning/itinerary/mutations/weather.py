"""Planning itinerary mutations weather."""

from __future__ import annotations

from datetime import timedelta
from travel_agent.planning.itinerary.models import CustomBlock
from travel_agent.planning.itinerary.models import VisitStop
from travel_agent.planning.itinerary.mutations.contracts import (
    ApplyWeatherAdjustmentMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import (
    CreateCustomBlockMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import (
    DismissWeatherAdjustmentMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import SelectOptionMutation
from travel_agent.planning.itinerary.mutations.contracts import SetTransportModeMutation
from travel_agent.planning.itinerary.mutations.contracts import (
    UpdateStopScheduleMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import (
    WorkspaceV2MutationApplication,
)
from travel_agent.planning.itinerary.mutations.contracts import WorkspaceV2MutationError
from travel_agent.planning.itinerary.mutations.results import _itinerary_result
from travel_agent.planning.itinerary.mutations.results import _snapshot_result
from travel_agent.planning.itinerary.mutations.selection import _apply_selection
from travel_agent.planning.itinerary.mutations.selection import _selection_reason
from travel_agent.planning.itinerary.mutations.selection import _slot
from travel_agent.planning.itinerary.mutations.timeline_operations import (
    apply_create_custom_block,
)
from travel_agent.planning.itinerary.mutations.timeline_operations import (
    apply_update_stop_schedule,
)
from travel_agent.planning.itinerary.mutations.transport import apply_set_transport_mode
from travel_agent.planning.itinerary.options import SelectionOption
from travel_agent.planning.references import EntityLineage
from travel_agent.planning.references import EntityRef
from travel_agent.planning.references import EntityType
from travel_agent.planning.research.candidates import VisitCandidate
from travel_agent.planning.weather.models import WeatherBufferOperation
from travel_agent.planning.weather.models import WeatherContextSnapshot
from travel_agent.planning.weather.models import WeatherProposalDecision
from travel_agent.planning.weather.models import WeatherRescheduleOperation
from travel_agent.planning.weather.models import WeatherSelectionOperation
from travel_agent.planning.weather.models import WeatherTransportModeOperation
from travel_agent.planning.weather.models import WeatherVisitReplacementOperation
from travel_agent.planning.workspace import TripWorkspaceV2
from typing import Optional


def _proposal(
    workspace: TripWorkspaceV2,
    weather: Optional[WeatherContextSnapshot],
    proposal_id: str,
):
    if weather is None:
        raise WorkspaceV2MutationError(
            "weather_snapshot_required",
            "Weather adjustment requires the current Weather snapshot",
        )
    proposal = next(
        (
            item
            for item in weather.adjustment_proposals
            if item.proposal_id == proposal_id
        ),
        None,
    )
    if proposal is None:
        raise WorkspaceV2MutationError(
            "weather_proposal_not_found", "Weather adjustment proposal does not exist"
        )
    if any(
        item.proposal_id == proposal_id for item in workspace.weather_proposal_decisions
    ):
        raise WorkspaceV2MutationError(
            "weather_proposal_resolved",
            "Weather adjustment proposal was already handled",
        )
    return proposal


def _replace_visit_candidate(
    workspace: TripWorkspaceV2,
    operation: WeatherVisitReplacementOperation,
) -> WorkspaceV2MutationApplication:
    itinerary = workspace.itinerary
    current = next(
        (item for item in itinerary.visit_stops if item.item_id == operation.item_id),
        None,
    )
    if current is None:
        raise WorkspaceV2MutationError("visit_not_found", "Visit target does not exist")
    if current.lineage.candidate_id != operation.expected_candidate_id:
        raise WorkspaceV2MutationError(
            "weather_proposal_stale", "Visit changed after the weather proposal"
        )
    candidate = workspace.recommendation_catalog.candidate_index().get(
        operation.candidate_id
    )
    if not isinstance(candidate, VisitCandidate):
        raise WorkspaceV2MutationError(
            "candidate_not_found",
            "Weather replacement candidate is missing from the catalog",
        )
    planned_end = (
        current.planned_start
        + timedelta(minutes=candidate.recommended_duration_minutes)
        if current.planned_start is not None
        else current.planned_end
    )
    updated = VisitStop(
        item_id=current.item_id,
        day_id=current.day_id,
        place_id=candidate.place_id,
        name=candidate.name,
        address=candidate.address,
        planned_start=current.planned_start,
        planned_end=planned_end,
        duration_minutes=candidate.recommended_duration_minutes,
        estimated_cost_cny=candidate.estimated_cost_cny,
        selection_reason=_selection_reason(
            SelectionOption(
                option_id=f"weather_{candidate.candidate_id}",
                selection_slot_id="weather_adjustment",
                candidate_id=candidate.candidate_id,
                candidate_entity_ref=EntityRef(
                    entity_type=EntityType.VISIT_STOP, entity_id=current.item_id
                ),
                rank=1,
                selection_reasons=candidate.selection_reasons,
                comparison_facts=candidate.field_paths,
                availability_status="confirmed",
                fact_assertion_ids=candidate.fact_assertion_ids,
                source_record_ids=candidate.source_record_ids,
                personalization_influence_ids=candidate.personalization_influence_ids,
            )
        ),
        lineage=EntityLineage(
            research_packet_id=candidate.research_packet_id,
            candidate_id=candidate.candidate_id,
            fact_assertion_ids=candidate.fact_assertion_ids,
            source_record_ids=candidate.source_record_ids,
            planning_decision_ids=candidate.planning_decision_ids,
            weather_impact_ids=candidate.weather_impact_ids,
            personalization_influence_ids=candidate.personalization_influence_ids,
        ),
        visit_type=candidate.visit_type,
        opening_window=candidate.opening_window,
        reservation_required=candidate.reservation_required,
        visit_highlights=candidate.highlights,
    )
    return _itinerary_result(
        workspace,
        itinerary.model_copy(
            update={
                "visit_stops": [
                    updated if item.item_id == current.item_id else item
                    for item in itinerary.visit_stops
                ],
            }
        ),
        f"替换为{updated.name}",
    )


def _operation_mutation(workspace: TripWorkspaceV2, operation):
    if isinstance(operation, WeatherRescheduleOperation):
        current = next(
            (
                item
                for item in [
                    *workspace.itinerary.visit_stops,
                    *workspace.itinerary.dining_stops,
                    *workspace.itinerary.custom_blocks,
                ]
                if item.item_id == operation.item_id
            ),
            None,
        )
        if (
            current is None
            or current.planned_start != operation.expected_planned_start
            or current.planned_end != operation.expected_planned_end
        ):
            raise WorkspaceV2MutationError(
                "weather_proposal_stale", "Schedule changed after the weather proposal"
            )
        return UpdateStopScheduleMutation(
            item_id=operation.item_id,
            planned_start=operation.planned_start,
            planned_end=operation.planned_end,
        )
    if isinstance(operation, WeatherSelectionOperation):
        slot = _slot(workspace, operation.selection_slot_id)
        if slot.selected_option_id != operation.expected_option_id:
            raise WorkspaceV2MutationError(
                "weather_proposal_stale", "Selection changed after the weather proposal"
            )
        return SelectOptionMutation(
            selection_slot_id=operation.selection_slot_id,
            option_id=operation.option_id,
        )
    if isinstance(operation, WeatherTransportModeOperation):
        leg = next(
            (
                item
                for item in workspace.itinerary.transport_legs
                if item.transport_leg_id == operation.transport_leg_id
            ),
            None,
        )
        if leg is None or leg.selected_mode != operation.expected_mode:
            raise WorkspaceV2MutationError(
                "weather_proposal_stale", "Transport changed after the weather proposal"
            )

        return SetTransportModeMutation(
            transport_leg_id=operation.transport_leg_id,
            selected_mode=operation.selected_mode,
            lock_mode=False,
        )
    if isinstance(operation, WeatherBufferOperation):
        day = next(
            (
                item
                for item in workspace.itinerary.day_plans
                if item.day_id == operation.day_id
            ),
            None,
        )
        if day is None:
            raise WorkspaceV2MutationError(
                "weather_proposal_stale", "Weather buffer day changed"
            )
        target_index = next(
            (
                index
                for index, item in enumerate(day.timeline)
                if item.entity_id == operation.target_entity_id
            ),
            None,
        )
        if target_index is None:
            raise WorkspaceV2MutationError(
                "weather_proposal_stale", "Weather buffer target changed"
            )
        before = (
            day.timeline[target_index + 1].entry_id
            if target_index + 1 < len(day.timeline)
            else None
        )
        return CreateCustomBlockMutation(
            block=CustomBlock(
                item_id=operation.block_id,
                day_id=operation.day_id,
                title="天气机动时间",
                note="为当天具体天气变化预留的执行缓冲",
                duration_minutes=operation.duration_minutes,
            ),
            before_entry_id=before,
        )
    return None


def _apply_weather_adjustment(
    workspace: TripWorkspaceV2,
    weather: Optional[WeatherContextSnapshot],
    mutation: ApplyWeatherAdjustmentMutation,
) -> WorkspaceV2MutationApplication:
    proposal = _proposal(workspace, weather, mutation.proposal_id)
    working = workspace
    changed = False
    for operation in proposal.operations:
        if isinstance(operation, WeatherVisitReplacementOperation):
            application = _replace_visit_candidate(working, operation)
        else:
            nested = _operation_mutation(working, operation)
            if nested is None:
                raise WorkspaceV2MutationError(
                    "weather_operation_unsupported",
                    "Weather proposal operation is unsupported",
                )
            if isinstance(nested, SelectOptionMutation):
                application = _apply_selection(working, nested)
            elif isinstance(nested, UpdateStopScheduleMutation):
                application = apply_update_stop_schedule(working, nested)
            elif isinstance(nested, SetTransportModeMutation):
                application = apply_set_transport_mode(working, nested)
            elif isinstance(nested, CreateCustomBlockMutation):
                application = apply_create_custom_block(working, nested)
            else:
                raise WorkspaceV2MutationError(
                    "unsupported_operation", "Unsupported workspace v2 mutation"
                )
        working = application.workspace
        changed = changed or application.changed
    if not changed:
        raise WorkspaceV2MutationError(
            "weather_proposal_no_change",
            "Weather proposal no longer changes the itinerary",
        )
    decisions = [
        *working.weather_proposal_decisions,
        WeatherProposalDecision(proposal_id=proposal.proposal_id, decision="applied"),
    ]
    return _snapshot_result(
        workspace,
        working.model_copy(update={"weather_proposal_decisions": decisions}),
        f"应用{proposal.date.isoformat()}天气调整",
    )


def apply_dismiss_weather_adjustment(
    workspace: TripWorkspaceV2,
    mutation: DismissWeatherAdjustmentMutation,
    weather_snapshot: Optional[WeatherContextSnapshot] = None,
) -> WorkspaceV2MutationApplication:
    proposal = _proposal(workspace, weather_snapshot, mutation.proposal_id)
    return _snapshot_result(
        workspace,
        workspace.model_copy(
            update={
                "weather_proposal_decisions": [
                    *workspace.weather_proposal_decisions,
                    WeatherProposalDecision(
                        proposal_id=proposal.proposal_id, decision="dismissed"
                    ),
                ]
            }
        ),
        "暂不采用天气调整",
    )
