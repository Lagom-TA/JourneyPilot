"""预算估算节点。"""

from __future__ import annotations

from typing import Any

from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.workspace import TripWorkspaceV2


async def budget_estimate_node(state: TravelAgentState) -> dict[str, Any]:
    """清除模型推断的总额，不调用模型或 provider。"""
    workspace = state.trip_workspace_v2
    if (
        workspace is None
        or workspace.itinerary.cost_summary.llm_estimated_total_cny is None
    ):
        return {}
    itinerary = workspace.itinerary
    summary = itinerary.cost_summary.model_copy(
        update={"llm_estimated_total_cny": None}
    )
    updated = TripWorkspaceV2.model_validate(
        workspace.model_copy(
            update={"itinerary": itinerary.model_copy(update={"cost_summary": summary})}
        ).model_dump(mode="json")
    )
    return {"trip_workspace_v2": updated}
