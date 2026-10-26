"""Planning research dispatch."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Set, Union

from langchain_core.runnables import RunnableConfig

from travel_agent.planning.assignments import strip_round_suffix
from travel_agent.planning.research.assembly import build_candidate_catalog
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.deadlines import observe_run_deadline

logger = logging.getLogger(__name__)


_NODE_NAME = "dispatcher"


_DONE_STATUSES = {"completed", "partial", "failed"}


_KNOWN_NEXT_AGENTS: Set[str] = {
    "to_check",
    "itinerary_planner",
    "dispatch_group",
}


def _composition_step(plan: Optional[list], from_step: int) -> Optional[int]:
    """Index of the plan's itinerary composition group at or after ``from_step``."""
    if not plan:
        return None
    for index in range(max(0, from_step), len(plan)):
        if any(
            strip_round_suffix(agent) == "itinerary_planner" for agent in plan[index]
        ):
            return index
    return None


def _pending_agents_in_group(state: TravelAgentState, group: list[str]) -> list[str]:
    """Return plan-group agent keys that are not yet in a terminal worker status."""
    return [
        agent for agent in group if state.agent_status.get(agent) not in _DONE_STATUSES
    ]


def _catalog_update(state: TravelAgentState) -> Dict[str, Any]:
    """Build the candidate catalog from the current worker packets.

    组合阶段开始前必须先把已有 packet 收敛成候选目录；部分 worker 失败时
    同样用剩余 packet 构建，行程组合再对空缺域自行失败。
    """
    catalog, impacts = build_candidate_catalog(state)
    return {
        "recommendation_catalog": catalog,
        "weather_impacts": {impact.weather_impact_id: impact for impact in impacts},
    }


async def dispatcher_node(
    state: TravelAgentState,
    config: Optional[RunnableConfig] = None,
) -> Dict[str, Any]:
    """Dispatcher 节点：推进执行计划，检查 worker 完成状态。"""
    plan = state.execution_plan
    step = state.current_plan_step

    deadline = state.run_deadline
    observed_deadline, observation = (
        observe_run_deadline(deadline) if deadline is not None else (None, None)
    )
    if observation is not None:
        deadline_update: Dict[str, Any] = {"run_deadline": observed_deadline}
        if observation.research_closed:
            composition_step = _composition_step(plan, step)
            owes_composition = (
                not observation.composition_closed
                and state.trip_workspace_v2 is None
                and composition_step is not None
            )
            if owes_composition:
                logger.info(
                    "Dispatcher: 研究窗口关闭，跳至行程组合 step=%s", composition_step
                )
                return {
                    **deadline_update,
                    **_catalog_update(state),
                    "current_plan_step": composition_step,
                    "next_agent": "itinerary_planner",
                }

            return {
                **deadline_update,
                "next_agent": "to_check",
            }

    if not plan or step >= len(plan):
        logger.info("Dispatcher: 计划已完成，路由到预算节点")
        return {"next_agent": "to_check"}

    current_group = plan[step]

    group_complete = all(
        state.agent_status.get(agent) in _DONE_STATUSES for agent in current_group
    )

    if not group_complete:
        logger.info(f"Dispatcher: 分发当前组 step={step}, group={current_group}")
        return {"next_agent": "dispatch_group"}

    next_step = step + 1
    if next_step < len(plan):
        next_group = plan[next_step]
        logger.info(f"Dispatcher: 推进到 step={next_step}, group={next_group}")
        update: Dict[str, Any] = {"current_plan_step": next_step}
        if any(
            strip_round_suffix(agent) == "itinerary_planner"
            for agent in next_group
        ):
            update.update(_catalog_update(state))
            update["next_agent"] = "itinerary_planner"
        else:
            update["next_agent"] = "dispatch_group"
        return update

    logger.info("Dispatcher: 计划已收尾，路由到预算节点")
    return {"next_agent": "to_check"}


def route_after_dispatcher(state: TravelAgentState) -> Union[str, list]:
    """LangGraph 条件边：根据 dispatcher 决策返回下一节点。"""
    next_agent = state.next_agent or "to_check"

    if next_agent not in _KNOWN_NEXT_AGENTS:
        logger.error(
            "Dispatcher: unknown next_agent=%r; converging on budget estimate",
            next_agent,
        )
        return "to_check"

    if next_agent == "to_check":
        return "to_check"

    if next_agent == "itinerary_planner":
        return "itinerary_planner"

    if next_agent == "dispatch_group":
        plan = state.execution_plan
        step = state.current_plan_step

        if plan and step < len(plan):
            current_group = plan[step]
            pending = _pending_agents_in_group(state, current_group)
            if not pending:
                logger.warning(
                    "Dispatcher: dispatch_group with no pending agents step=%s group=%s",
                    step,
                    current_group,
                )
                return "to_check"

            resolved_group = [strip_round_suffix(a) for a in pending]

            if len(resolved_group) > 1:
                from langgraph.types import Send

                return [Send(node, state) for node in resolved_group]
            return resolved_group[0]

        logger.error(
            "Dispatcher: dispatch_group without a valid plan step; "
            "converging on budget estimate"
        )
        return "to_check"

    logger.error(
        "Dispatcher: unhandled next_agent=%r; converging on budget estimate",
        next_agent,
    )
    return "to_check"
