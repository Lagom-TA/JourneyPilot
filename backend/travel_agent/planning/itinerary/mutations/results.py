"""Planning itinerary mutations results."""

from __future__ import annotations

from travel_agent.planning.itinerary.models import StructuredItineraryV2
from travel_agent.planning.itinerary.mutations.contracts import ItineraryInversePatch
from travel_agent.planning.itinerary.mutations.contracts import (
    WorkspaceSnapshotInversePatch,
)
from travel_agent.planning.itinerary.mutations.contracts import (
    WorkspaceV2MutationApplication,
)
from travel_agent.planning.itinerary.mutations.timeline import _drop_stale_day_notes
from travel_agent.planning.itinerary.mutations.timeline import (
    _invalidate_changed_connectors,
)
from travel_agent.planning.itinerary.mutations.timeline import (
    _validate_changed_stop_windows,
)
from travel_agent.planning.workspace import TripWorkspaceV2


def _validated_workspace(
    workspace: TripWorkspaceV2,
    itinerary: StructuredItineraryV2,
    *,
    restore_day_notes: bool = False,
) -> TripWorkspaceV2:
    _validate_changed_stop_windows(workspace, itinerary)
    itinerary = _invalidate_changed_connectors(itinerary)
    if not restore_day_notes:
        itinerary = _drop_stale_day_notes(workspace, itinerary)
    return TripWorkspaceV2.model_validate(
        workspace.model_copy(
            update={
                "workspace_revision": workspace.workspace_revision + 1,
                "itinerary": itinerary,
                "intent_coverage_report": None,
            }
        ).model_dump(mode="json")
    )


def _itinerary_result(
    workspace: TripWorkspaceV2, itinerary: StructuredItineraryV2, label: str
) -> WorkspaceV2MutationApplication:
    if itinerary == workspace.itinerary:
        return WorkspaceV2MutationApplication(workspace=workspace, changed=False)
    next_workspace = _validated_workspace(workspace, itinerary)
    return WorkspaceV2MutationApplication(
        workspace=next_workspace,
        changed=True,
        label=label,
        inverse=ItineraryInversePatch(
            applied_workspace_revision=next_workspace.workspace_revision,
            previous_itinerary=workspace.itinerary,
        ),
    )


def _snapshot_result(
    workspace: TripWorkspaceV2,
    following: TripWorkspaceV2,
    label: str,
) -> WorkspaceV2MutationApplication:
    if following == workspace:
        return WorkspaceV2MutationApplication(workspace=workspace, changed=False)
    _validate_changed_stop_windows(workspace, following.itinerary)
    following = following.model_copy(
        update={
            "itinerary": _drop_stale_day_notes(
                workspace, _invalidate_changed_connectors(following.itinerary)
            )
        }
    )
    next_workspace = TripWorkspaceV2.model_validate(
        following.model_copy(
            update={
                "workspace_revision": workspace.workspace_revision + 1,
                "intent_coverage_report": None,
            }
        ).model_dump(mode="json")
    )
    return WorkspaceV2MutationApplication(
        workspace=next_workspace,
        changed=True,
        label=label,
        inverse=WorkspaceSnapshotInversePatch(
            applied_workspace_revision=next_workspace.workspace_revision,
            previous_workspace=workspace,
        ),
    )
