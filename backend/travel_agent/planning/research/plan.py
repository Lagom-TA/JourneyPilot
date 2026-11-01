"""把研究方案中的任务交给对应角色。"""

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


# 研究执行计划的唯一真值：目的地 → 交通 → 住宿 → 组合，串行推进，
# 后一位角色读取前序成果。计划门禁展示与批准落章都使用同一份定义。
RESEARCH_EXECUTION_PLAN: list[list[str]] = [
    ["destination_researcher"],
    ["transport_researcher"],
    ["accommodation_researcher"],
    ["itinerary_planner"],
]


async def planner_node(state: TravelAgentState) -> Dict[str, Any]:
    plan = state.research_plan
    if plan is None or state.planning_generation is None:
        raise ValueError("任务分派需要当前研究方案")
    assignments = {worker: {"objective": task} for worker, task in plan.tasks().items()}
    legs = build_required_long_distance_legs(
        state.controlled_trip_identity or {},
        cross_day_return_required=False,
    )
    for worker in ("destination_researcher", "transport_researcher", "accommodation_researcher"):
        assignments[worker]["provider_evidence_assignments"] = dump_provider_evidence_assignments(
            build_provider_evidence_assignments(
                run_id=state.run_id,
                worker_kind=worker,
                controlled_trip_identity=state.controlled_trip_identity or {},
                prior_scope_attempts=scope_attempt_numbers(state.provider_evidence_outcomes),
                transport_classes=(["public_transit", "flexible"] if worker == "transport_researcher" and not legs else None),
                long_distance_legs=legs if worker == "transport_researcher" else None,
            )
        )
    return {
        "execution_plan": RESEARCH_EXECUTION_PLAN,
        "current_plan_step": 0,
        "agent_assignments": assignments,
        "task_type": TaskType.TRAVEL_PLANNING,
    }
