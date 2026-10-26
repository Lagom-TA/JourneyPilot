from __future__ import annotations

from typing import Any, Dict

from travel_agent.planning.research.brief_builder import (
    RESEARCH_BRIEF_POLICY_VERSION,
    build_research_brief,
)
from travel_agent.planning.state import TravelAgentState


async def research_brief_builder_node(state: TravelAgentState) -> Dict[str, Any]:
    if state.request_contract is None:
        raise ValueError("research brief requires a request contract")
    brief = build_research_brief(
        state.request_contract,
        state.controlled_trip_identity,
    )
    return {
        "research_brief": brief,
        "next_agent": None,
        "policy_versions": {
            "research_brief_projection": RESEARCH_BRIEF_POLICY_VERSION,
        },
    }
