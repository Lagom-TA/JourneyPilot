from __future__ import annotations

from typing import Any, Dict

from travel_agent.conversation.contracts import TaskType
from travel_agent.planning.requirements.route_legs import (
    build_required_long_distance_legs,
    explicit_cross_day_return_required,
)
from travel_agent.planning.research.capability_planning import (
    CAPABILITY_PLAN_POLICY_VERSION,
    build_capability_plan,
)
from travel_agent.planning.research.provider_assignments import (
    build_provider_evidence_assignments,
    dump_provider_evidence_assignments,
    scope_attempt_numbers,
)
from travel_agent.planning.research.query_planner import (
    RESEARCH_QUERY_POLICY_VERSION,
    build_research_query_plan,
)
from travel_agent.planning.state import TravelAgentState


def _attach_initial_provider_evidence_scopes(
    assignments: Dict[str, Dict[str, Any]],
    state: TravelAgentState,
) -> Dict[str, Dict[str, Any]]:
    scoped = {key: dict(value) for key, value in assignments.items()}
    long_distance_legs = build_required_long_distance_legs(
        state.controlled_trip_identity or {},
        cross_day_return_required=explicit_cross_day_return_required(
            state.user_query or ""
        ),
    )
    for worker in (
        "destination_researcher",
        "transport_researcher",
        "accommodation_researcher",
    ):
        if worker not in scoped:
            continue
        scoped[worker]["provider_evidence_assignments"] = (
            dump_provider_evidence_assignments(
                build_provider_evidence_assignments(
                    run_id=state.run_id,
                    constraint_pack_revision=state.constraint_pack_revision,
                    worker_kind=worker,
                    controlled_trip_identity=state.controlled_trip_identity or {},
                    prior_scope_attempts=scope_attempt_numbers(
                        state.provider_evidence_outcomes
                    ),
                    transport_classes=(
                        ["public_transit", "flexible"]
                        if worker == "transport_researcher" and not long_distance_legs
                        else None
                    ),
                    long_distance_legs=(
                        long_distance_legs if worker == "transport_researcher" else None
                    ),
                )
            )
        )
    return scoped


async def planner_node(state: TravelAgentState) -> Dict[str, Any]:
    if state.request_contract is None or state.research_brief is None:
        raise ValueError(
            "capability planning requires a request contract and research brief"
        )
    if state.planning_generation is None:
        raise ValueError("capability planning requires a planning generation")
    query_plan = build_research_query_plan(
        intent_spec=state.request_contract.intent_spec,
        brief=state.research_brief,
    )
    plan = build_capability_plan(
        request_contract=state.request_contract,
        brief=state.research_brief,
        plan_revision=state.planning_generation.plan_revision,
        research_query_plan=query_plan,
    )
    assignments = {
        key: value.model_dump(mode="json") for key, value in plan.assignments.items()
    }
    assignments = _attach_initial_provider_evidence_scopes(assignments, state)
    return {
        "capability_plan": plan,
        "research_query_plan": query_plan,
        "execution_plan": plan.execution_plan,
        "current_plan_step": 0,
        "agent_assignments": assignments,
        "task_type": TaskType.TRAVEL_PLANNING,
        "policy_versions": {
            "capability_plan": CAPABILITY_PLAN_POLICY_VERSION,
            "research_query_plan": RESEARCH_QUERY_POLICY_VERSION,
        },
    }
