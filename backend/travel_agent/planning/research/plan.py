"""把已确认的研究设想交给各角色。"""

from __future__ import annotations

from typing import Any, Dict

from travel_agent.conversation.contracts import TaskType
from travel_agent.planning.requirements.route_legs import build_required_long_distance_legs
from travel_agent.planning.research.provider_assignments import (
    build_provider_evidence_assignments,
    dump_provider_evidence_assignments,
    scope_attempt_numbers,
)
from travel_agent.planning.state import TravelAgentState


# 确认展示与实际分发使用同一份计划；同组角色并行研究。
RESEARCH_EXECUTION_PLAN: list[list[str]] = [
    ["destination_researcher"],
    ["transport_researcher", "accommodation_researcher"],
    ["itinerary_planner"],
]


def build_worker_assignment(
    state: TravelAgentState, worker: str, objective: str
) -> Dict[str, Any]:
    """构造研究 Worker 的任务分配；provider 证据范围按已发生尝试续编。"""
    legs = build_required_long_distance_legs(
        state.controlled_trip_identity or {},
        cross_day_return_required=False,
    )
    return {
        "objective": objective,
        "provider_evidence_assignments": dump_provider_evidence_assignments(
            build_provider_evidence_assignments(
                run_id=state.run_id,
                worker_kind=worker,
                controlled_trip_identity=state.controlled_trip_identity or {},
                prior_scope_attempts=scope_attempt_numbers(
                    state.provider_evidence_outcomes
                ),
                transport_classes=(
                    ["public_transit", "flexible"]
                    if worker == "transport_researcher" and not legs
                    else None
                ),
                long_distance_legs=legs if worker == "transport_researcher" else None,
            )
        ),
    }


async def planner_node(state: TravelAgentState) -> Dict[str, Any]:
    plan = state.research_plan
    if plan is None or state.planning_generation is None:
        raise ValueError("任务分派需要当前研究方案")
    assignments = {
        worker: build_worker_assignment(state, worker, plan.summary)
        for group in RESEARCH_EXECUTION_PLAN
        for worker in group
        if worker != "itinerary_planner"
    }
    assignments["itinerary_planner"] = {"objective": plan.summary}
    return {
        "execution_plan": RESEARCH_EXECUTION_PLAN,
        "current_plan_step": 0,
        "agent_assignments": assignments,
        "task_type": TaskType.TRAVEL_PLANNING,
    }
