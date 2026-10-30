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
    from travel_agent.planning.requirements.revision import (
        request_contract_with_research_plan,
    )
    from travel_agent.planning.research.authorized_candidates import (
        build_authorized_candidate_selection,
    )

    confirmation_digest = request_contract_with_research_plan(
        state.request_contract, None
    ).content_hash
    candidate_selection = build_authorized_candidate_selection(
        state.request_contract,
        state.controlled_trip_identity,
        confirmation_digest,
    )
    brief = build_research_brief(
        state.request_contract,
        state.controlled_trip_identity,
        candidate_selection=candidate_selection,
        confirmation_digest=confirmation_digest,
    )
    return {
        "research_brief": brief,
        "next_agent": None,
        "policy_versions": {
            "research_brief_projection": RESEARCH_BRIEF_POLICY_VERSION,
        },
    }
