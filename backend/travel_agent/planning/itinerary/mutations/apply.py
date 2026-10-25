"""Planning itinerary mutations apply."""

from __future__ import annotations

from travel_agent.planning.itinerary.mutations.contracts import (
    ApplyWeatherAdjustmentMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import (
    CreateCustomBlockMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import (
    DeleteCustomBlockMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import (
    DeleteLodgingStayMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import (
    DeleteTransportLegMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import (
    DismissWeatherAdjustmentMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import MoveTimelineItemMutation
from travel_agent.planning.itinerary.mutations.contracts import SelectOptionMutation
from travel_agent.planning.itinerary.mutations.contracts import SetTransportModeMutation
from travel_agent.planning.itinerary.mutations.contracts import (
    UpdateCustomBlockMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import (
    UpdateStopScheduleMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import (
    UpdateTransportModePreferenceMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import WorkspaceV2Mutation
from travel_agent.planning.itinerary.mutations.contracts import (
    WorkspaceV2MutationApplication,
)
from travel_agent.planning.itinerary.mutations.contracts import WorkspaceV2MutationError
from travel_agent.planning.itinerary.mutations.selection import _apply_selection
from travel_agent.planning.itinerary.mutations.selection import (
    apply_delete_lodging_stay,
)
from travel_agent.planning.itinerary.mutations.timeline_operations import (
    apply_create_custom_block,
)
from travel_agent.planning.itinerary.mutations.timeline_operations import (
    apply_delete_custom_block,
)
from travel_agent.planning.itinerary.mutations.timeline_operations import (
    apply_move_timeline_item,
)
from travel_agent.planning.itinerary.mutations.timeline_operations import (
    apply_update_custom_block,
)
from travel_agent.planning.itinerary.mutations.timeline_operations import (
    apply_update_stop_schedule,
)
from travel_agent.planning.itinerary.mutations.transport import (
    apply_delete_transport_leg,
)
from travel_agent.planning.itinerary.mutations.transport import apply_set_transport_mode
from travel_agent.planning.itinerary.mutations.transport import (
    apply_update_transport_mode_preference,
)
from travel_agent.planning.itinerary.mutations.weather import _apply_weather_adjustment
from travel_agent.planning.itinerary.mutations.weather import (
    apply_dismiss_weather_adjustment,
)
from travel_agent.planning.weather.models import WeatherContextSnapshot
from travel_agent.planning.workspace import TripWorkspaceV2
from typing import Optional


def apply_workspace_v2_mutation(
    workspace: TripWorkspaceV2,
    mutation: WorkspaceV2Mutation,
    weather_snapshot: Optional[WeatherContextSnapshot] = None,
) -> WorkspaceV2MutationApplication:
    if isinstance(mutation, ApplyWeatherAdjustmentMutation):
        return _apply_weather_adjustment(workspace, weather_snapshot, mutation)
    if isinstance(mutation, DismissWeatherAdjustmentMutation):
        return apply_dismiss_weather_adjustment(workspace, mutation, weather_snapshot)
    if isinstance(mutation, SelectOptionMutation):
        return _apply_selection(workspace, mutation)
    if isinstance(mutation, MoveTimelineItemMutation):
        return apply_move_timeline_item(workspace, mutation)
    if isinstance(mutation, UpdateStopScheduleMutation):
        return apply_update_stop_schedule(workspace, mutation)
    if isinstance(mutation, CreateCustomBlockMutation):
        return apply_create_custom_block(workspace, mutation)
    if isinstance(mutation, UpdateCustomBlockMutation):
        return apply_update_custom_block(workspace, mutation)
    if isinstance(mutation, DeleteCustomBlockMutation):
        return apply_delete_custom_block(workspace, mutation)
    if isinstance(mutation, DeleteTransportLegMutation):
        return apply_delete_transport_leg(workspace, mutation)
    if isinstance(mutation, DeleteLodgingStayMutation):
        return apply_delete_lodging_stay(workspace, mutation)
    if isinstance(mutation, UpdateTransportModePreferenceMutation):
        return apply_update_transport_mode_preference(workspace, mutation)
    if isinstance(mutation, SetTransportModeMutation):
        return apply_set_transport_mode(workspace, mutation)
    raise WorkspaceV2MutationError(
        "unsupported_operation", "Unsupported workspace v2 mutation"
    )
