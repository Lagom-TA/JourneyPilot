from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Set

from langchain_core.runnables import RunnableConfig

from travel_agent.planning.assignments import resolve_agent_assignment, strip_round_suffix
from travel_agent.planning.nodes import NODE_DELIVERY_FINALIZER, NODE_ITINERARY, RESEARCH_WORKER_NODES
from travel_agent.planning.outcomes import (
    DeliveryFailureRecord,
    InternalFailureClass,
)
from travel_agent.planning.research.assembly import build_candidate_catalog
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.deadlines import observe_run_deadline, utc_now

logger = logging.getLogger(__name__)


_NODE_NAME = "dispatcher"


_DONE_STATUSES = {"completed", "partial", "failed"}


_KNOWN_NEXT_AGENTS: Set[str] = {
    "to_check",
    "itinerary_planner",
    "dispatch_group",
    "research_gate",
}


def _composition_step(plan: Optional[list], from_step: int) -> Optional[int]:
    """返回 ``from_step`` 起（含该步）第一个含行程组合的步骤下标。"""
    if not plan:
        return None
    for index in range(max(0, from_step), len(plan)):
        if any(
            strip_round_suffix(agent) == "itinerary_planner" for agent in plan[index]
        ):
            return index
    return None


def _status_key(state: TravelAgentState, agent: str) -> str:
    base = strip_round_suffix(agent)
    if base in RESEARCH_WORKER_NODES:
        try:
            return resolve_agent_assignment(state.agent_assignments, base)[0]
        except ValueError:
            pass
    return agent


def _pending_agents_in_group(state: TravelAgentState, group: list[str]) -> list[str]:
    """返回当前计划组中尚未进入终止状态的 agent key。"""
    pending = []
    for agent in group:
        if state.agent_status.get(_status_key(state, agent)) not in _DONE_STATUSES:
            pending.append(agent)
    return pending


def _catalog_update(state: TravelAgentState) -> Dict[str, Any]:
    """用当前研究成果构建候选目录。"""
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
    if state.research_retry_workers:
        retry_status = [
            state.agent_status.get(resolve_agent_assignment(state.agent_assignments, worker)[0])
            for worker in state.research_retry_workers
        ]
        if any(status not in _DONE_STATUSES for status in retry_status):
            return {"next_agent": "dispatch_group"}
        retry_update: Dict[str, Any] = {"research_retry_workers": []}
        state = state.model_copy(update={"research_retry_workers": []})
        retry_finished = True
    else:
        retry_update = {}
        retry_finished = False

    failed = []
    for worker in RESEARCH_WORKER_NODES:
        try:
            key, _ = resolve_agent_assignment(state.agent_assignments, worker)
        except ValueError:
            continue
        if state.agent_status.get(key) in {"failed", "partial"}:
            failed.append(worker)
    if failed:
        observed = observe_run_deadline(state.run_deadline)[0] if state.run_deadline else None
        return {
            **retry_update,
            **({"run_deadline": observed} if observed else {}),
            "next_agent": "research_gate",
            "research_failed_workers": sorted(failed),
            "research_gate_started_at": utc_now().isoformat(),
        }

    deadline = state.run_deadline
    observed_deadline, observation = (
        observe_run_deadline(deadline) if deadline is not None else (None, None)
    )
    if state.trip_workspace is None and state.agent_status.get(NODE_ITINERARY) == "failed":
        logger.error(
            "Dispatcher: 行程组合失败 run_id=%s context=%s last_error=%s",
            state.run_id,
            state.composition_failure_context,
            state.last_error,
        )
        failure_update: Dict[str, Any] = {
            "next_agent": "to_check",
            "delivery_failure": state.delivery_failure or DeliveryFailureRecord(
                failure_class=InternalFailureClass.UNCLASSIFIED,
                operation=NODE_ITINERARY,
                attempts=1,
                retry_exhausted=True,
                public_message="行程组合失败，请稍后重试。",
            ),
        }
        if observation is not None:
            failure_update["run_deadline"] = observed_deadline
        return failure_update

    if observation is not None:
        deadline_update: Dict[str, Any] = {"run_deadline": observed_deadline}
        if observation.research_closed:
            unfinished = [
                strip_round_suffix(worker)
                for group in (plan or [])
                for worker in group
                if strip_round_suffix(worker) in RESEARCH_WORKER_NODES
                and state.agent_status.get(_status_key(state, worker)) != "completed"
            ]
            if unfinished:
                return {
                    **retry_update,
                    **deadline_update,
                    "next_agent": "research_gate",
                    "research_failed_workers": sorted(unfinished),
                    "research_gate_started_at": utc_now().isoformat(),
                }
            composition_step = _composition_step(plan, step)
            owes_composition = (
                not observation.composition_closed
                and state.trip_workspace is None
                and composition_step is not None
                # 组合已失败（预算耗尽、返研上限等）时不再重入，
                # 直接收敛到预算与交付收口。
                and "failed"
                not in {
                    state.agent_status.get(strip_round_suffix(agent))
                    for agent in plan[composition_step]
                }
            )
            if owes_composition:
                logger.info(
                    "Dispatcher: 研究窗口关闭，跳至行程组合 step=%s", composition_step
                )
                return {
                    **retry_update,
                    **deadline_update,
                    **_catalog_update(state),
                    "current_plan_step": composition_step,
                    "next_agent": "itinerary_planner",
                }

            closeout: Dict[str, Any] = {
                **retry_update,
                **deadline_update,
                "next_agent": "to_check",
            }
            if state.trip_workspace is None:
                # 窗口关闭且没有产出可交付的组合：属于内容缺口，不是依赖
                # 瞬时故障。带着失败记录直连交付定稿，不再让 projector 抛错。
                closeout["delivery_failure"] = DeliveryFailureRecord(
                    failure_class=InternalFailureClass.RESEARCH_GAP,
                    operation="deadline_closeout",
                    attempts=1,
                    retry_exhausted=True,
                    public_message="未能在时限内完成行程组合，请稍后重试。",
                )
            return closeout

    if not plan or step >= len(plan):
        logger.info("Dispatcher: 计划已完成，路由到交付投影")
        return {**retry_update, "next_agent": "to_check"}

    current_group = plan[step]
    if retry_finished and any(strip_round_suffix(agent) == "itinerary_planner" for agent in current_group):
        return {**retry_update, **_catalog_update(state), "next_agent": "itinerary_planner"}

    group_complete = all(
        state.agent_status.get(_status_key(state, agent)) in _DONE_STATUSES
        for agent in current_group
    )

    if not group_complete:
        logger.info(f"Dispatcher: 分发当前组 step={step}, group={current_group}")
        update: Dict[str, Any] = {**retry_update, "next_agent": "dispatch_group"}
        # 组合重入前重建候选目录：返研轮的新 packet 需要进入组合可见的目录。
        if any(
            strip_round_suffix(agent) == "itinerary_planner"
            for agent in current_group
        ):
            update.update(_catalog_update(state))
        return update

    next_step = step + 1
    if next_step < len(plan):
        next_group = plan[next_step]
        logger.info(f"Dispatcher: 推进到 step={next_step}, group={next_group}")
        update: Dict[str, Any] = {**retry_update, "current_plan_step": next_step}
        if any(
            strip_round_suffix(agent) == "itinerary_planner"
            for agent in next_group
        ):
            update.update(_catalog_update(state))
            update["next_agent"] = "itinerary_planner"
        else:
            update["next_agent"] = "dispatch_group"
        return update

    logger.info("Dispatcher: 计划已收尾，路由到交付投影")
    return {**retry_update, "next_agent": "to_check"}


def route_after_dispatcher(state: TravelAgentState) -> str | list:
    """LangGraph 条件边：根据 dispatcher 决策返回下一节点。"""
    if state.delivery_failure is not None:
        return NODE_DELIVERY_FINALIZER

    next_agent = state.next_agent or "to_check"

    if next_agent not in _KNOWN_NEXT_AGENTS:
        logger.error(
            "Dispatcher: unknown next_agent=%r; converging on delivery projection",
            next_agent,
        )
        return "to_check"

    if next_agent == "to_check":
        return "to_check"

    if next_agent == "itinerary_planner":
        return "itinerary_planner"

    if next_agent == "research_gate":
        return "research_gate"

    if next_agent == "dispatch_group":
        if state.research_retry_workers:
            from langgraph.types import Send

            pending = [
                worker for worker in state.research_retry_workers
                if state.agent_status.get(resolve_agent_assignment(state.agent_assignments, worker)[0])
                not in _DONE_STATUSES
            ]
            return [Send(worker, state) for worker in pending]
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
            "converging on delivery projection"
        )
        return "to_check"

    logger.error(
        "Dispatcher: unhandled next_agent=%r; converging on delivery projection",
        next_agent,
    )
    return "to_check"
