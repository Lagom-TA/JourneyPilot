"""Keep the itemized budget without manufacturing prices for missing components.

The graph node is retained for checkpoint compatibility. Component prices and
externally supported reference estimates remain in the normal cost summary;
missing prices are disclosed with their item names in the report projection.
A legacy model total has no itemized assumptions or evidence, so it is cleared.
"""

from __future__ import annotations

from typing import Any

from travel_agent.planning.workspace import TripWorkspaceV2

from travel_agent.planning.state import TravelAgentState


async def budget_estimate_node(state: TravelAgentState) -> dict[str, Any]:
    """Remove a legacy unsupported total, without a model or provider call."""
    workspace = state.trip_workspace_v2
    if workspace is None or workspace.itinerary.cost_summary.llm_estimated_total_cny is None:
        return {}
    itinerary = workspace.itinerary
    summary = itinerary.cost_summary.model_copy(update={"llm_estimated_total_cny": None})
    updated = TripWorkspaceV2.model_validate(
        workspace.model_copy(
            update={"itinerary": itinerary.model_copy(update={"cost_summary": summary})}
        ).model_dump(mode="json")
    )
    return {"trip_workspace_v2": updated}
