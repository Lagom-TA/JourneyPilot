from __future__ import annotations

from typing import Any, Dict

from travel_agent.llm.router import get_model_router
from travel_agent.llm.task_routing import TaskKind, llm_for_task
from travel_agent.planning.requirements.clarification_questions import (
    necessary_requirement_questions,
)
from travel_agent.planning.requirements.revision import request_contract_with_research_plan
from travel_agent.planning.research.authorized_candidates import (
    build_authorized_candidate_selection,
)
from travel_agent.planning.research.plan_from_selection import plan_from_authorized_selection
from travel_agent.planning.research.selection import (
    CandidateSelectionStatus,
    select_research_candidates,
)
from travel_agent.planning.state import TravelAgentState


RESEARCH_PLAN_NODE_POLICY_VERSION = "research_plan_candidate_selection.v1"


async def research_plan_generator_node(state: TravelAgentState) -> Dict[str, Any]:
    contract = state.request_contract
    if contract is None:
        raise ValueError("model research planning requires a clarified request contract")
    candidate_contract = request_contract_with_research_plan(contract, None)
    if necessary_requirement_questions(state, candidate_contract):
        raise ValueError("research planning must wait for the remaining requirement answers")
    selection_input = build_authorized_candidate_selection(
        candidate_contract,
        state.controlled_trip_identity,
        candidate_contract.content_hash,
    )
    result = await select_research_candidates(
        selection_input,
        llm_for_task(get_model_router(), TaskKind.INTENT_NORMALIZE),
    )
    if result.status is not CandidateSelectionStatus.SELECTED:
        failure = result.failure
        return {
            "request_contract": candidate_contract,
            "research_plan_error": {
                "code": failure.code.value if failure else "model_output_invalid",
                "detail": failure.detail if failure else "model selection failed",
            },
            "policy_versions": {"research_plan_generation": RESEARCH_PLAN_NODE_POLICY_VERSION},
        }
    try:
        plan = plan_from_authorized_selection(selection_input, result)
    except (TypeError, ValueError):
        return {
            "request_contract": candidate_contract,
            "research_plan_error": {
                "code": "model_output_invalid",
                "detail": "model selection could not be compiled into the authorized plan",
            },
            "policy_versions": {"research_plan_generation": RESEARCH_PLAN_NODE_POLICY_VERSION},
        }
    return {
        "request_contract": request_contract_with_research_plan(candidate_contract, plan),
        "request_contract_candidate": None,
        "research_plan_error": None,
        "research_plan_retry_count": 0,
        "policy_versions": {"research_plan_generation": RESEARCH_PLAN_NODE_POLICY_VERSION},
    }
