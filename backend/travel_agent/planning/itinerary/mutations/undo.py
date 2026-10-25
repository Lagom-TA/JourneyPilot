"""Planning itinerary mutations undo."""

from __future__ import annotations

from travel_agent.planning.itinerary.models import DiningStop
from travel_agent.planning.itinerary.models import TransportLeg
from travel_agent.planning.itinerary.models import VisitStop
from travel_agent.planning.itinerary.mutations.contracts import ItineraryInversePatch
from travel_agent.planning.itinerary.mutations.contracts import SelectionInversePatch
from travel_agent.planning.itinerary.mutations.contracts import (
    WorkspaceSnapshotInversePatch,
)
from travel_agent.planning.itinerary.mutations.contracts import WorkspaceV2InversePatch
from travel_agent.planning.itinerary.mutations.contracts import WorkspaceV2MutationError
from travel_agent.planning.itinerary.mutations.derived_fields import (
    _recompute_derived_itinerary_fields,
)
from travel_agent.planning.itinerary.mutations.results import _validated_workspace
from travel_agent.planning.itinerary.mutations.selection import _option
from travel_agent.planning.itinerary.mutations.selection import _slot
from travel_agent.planning.workspace import TripWorkspaceV2


def apply_workspace_v2_inverse(
    workspace: TripWorkspaceV2,
    inverse: WorkspaceV2InversePatch,
    *,
    allow_data_refresh_rebase: bool = False,
) -> TripWorkspaceV2:
    if workspace.workspace_revision != inverse.applied_workspace_revision and not (
        allow_data_refresh_rebase
        and not isinstance(inverse, WorkspaceSnapshotInversePatch)
        and workspace.workspace_revision > inverse.applied_workspace_revision
    ):
        raise WorkspaceV2MutationError(
            "undo_head_mismatch", "Workspace changed since this mutation"
        )
    if isinstance(inverse, ItineraryInversePatch):
        return _validated_workspace(
            workspace, inverse.previous_itinerary, restore_day_notes=True
        )
    if isinstance(inverse, WorkspaceSnapshotInversePatch):
        if inverse.previous_workspace.run_id != workspace.run_id:
            raise WorkspaceV2MutationError(
                "inverse_run_mismatch", "Inverse workspace belongs to another run"
            )
        return TripWorkspaceV2.model_validate(
            inverse.previous_workspace.model_copy(
                update={
                    "workspace_revision": workspace.workspace_revision + 1,
                }
            ).model_dump(mode="json")
        )
    return apply_selection_inverse(
        workspace,
        inverse,
        allow_data_refresh_rebase=allow_data_refresh_rebase,
    )


def apply_selection_inverse(
    workspace: TripWorkspaceV2,
    inverse: SelectionInversePatch,
    *,
    allow_data_refresh_rebase: bool = False,
) -> TripWorkspaceV2:
    if workspace.workspace_revision != inverse.applied_workspace_revision and not (
        allow_data_refresh_rebase
        and workspace.workspace_revision > inverse.applied_workspace_revision
    ):
        raise WorkspaceV2MutationError(
            "undo_head_mismatch", "Workspace changed since this mutation"
        )
    slot = _slot(workspace, inverse.selection_slot_id)
    if slot.selected_option_id != inverse.applied_option_id:
        raise WorkspaceV2MutationError(
            "undo_head_mismatch", "Selection changed since this mutation"
        )
    if inverse.previous_selected_option_id is not None:
        previous_option = _option(slot, inverse.previous_selected_option_id)
        if previous_option.candidate_id != inverse.previous_entity.lineage.candidate_id:
            raise WorkspaceV2MutationError(
                "inverse_lineage_mismatch",
                "Inverse entity does not match previous option",
            )
    itinerary = workspace.itinerary
    if isinstance(inverse.previous_entity, DiningStop):
        itinerary = itinerary.model_copy(
            update={
                "dining_stops": [
                    inverse.previous_entity
                    if item.item_id == inverse.previous_entity.item_id
                    else item
                    for item in itinerary.dining_stops
                ],
            }
        )
    elif isinstance(inverse.previous_entity, VisitStop):
        itinerary = itinerary.model_copy(
            update={
                "visit_stops": [
                    inverse.previous_entity
                    if item.item_id == inverse.previous_entity.item_id
                    else item
                    for item in itinerary.visit_stops
                ],
            }
        )
    elif isinstance(inverse.previous_entity, TransportLeg):
        itinerary = itinerary.model_copy(
            update={
                "transport_legs": [
                    inverse.previous_entity
                    if item.transport_leg_id == inverse.previous_entity.transport_leg_id
                    else item
                    for item in itinerary.transport_legs
                ],
            }
        )
    else:
        itinerary = itinerary.model_copy(
            update={
                "lodging_stays": [
                    inverse.previous_entity
                    if item.stay_id == inverse.previous_entity.stay_id
                    else item
                    for item in itinerary.lodging_stays
                ],
            }
        )
    itinerary = _recompute_derived_itinerary_fields(itinerary)
    next_slot = slot.model_copy(
        update={
            "selected_option_id": inverse.previous_selected_option_id,
            "status": inverse.previous_slot_status,
        }
    )
    return TripWorkspaceV2.model_validate(
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
