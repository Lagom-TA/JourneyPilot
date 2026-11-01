"""规划工作流图。"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from langgraph.graph import END, START, StateGraph

from travel_agent.planning.costs.estimate import budget_estimate_node
from travel_agent.planning.delivery.finalizer import delivery_finalizer_node
from travel_agent.planning.delivery.minimum_draft import (
    minimum_delivery_draft_builder_node,
)
from travel_agent.planning.delivery.projection_node import delivery_projection_node
from travel_agent.planning.execution import with_run_control
from travel_agent.planning.itinerary.node import itinerary_planner_node
from travel_agent.planning.nodes import (
    NODE_ACCOMMODATION,
    NODE_BUDGET_ESTIMATE,
    NODE_CLARIFIER,
    NODE_DELIVERY_FINALIZER,
    NODE_DELIVERY_PROJECTOR,
    NODE_DESTINATION,
    NODE_DESTINATION_GEO_RESOLVER,
    NODE_DISPATCHER,
    NODE_INTENT_AMENDMENT_ROUTER,
    NODE_ITINERARY,
    NODE_MINIMUM_DELIVERY_DRAFT,
    NODE_PLAN_GATE,
    NODE_PLANNER,
    NODE_REQUIREMENTS_PREPARER,
    NODE_RESEARCH_PLAN_GENERATOR,
    NODE_SUMMARY_CARD_BRIEF,
    NODE_TRANSPORT,
    NODE_UNDERSTANDING_AGENT,
    NODE_UNDERSTANDING_GATE,
    NODE_WEATHER_CONTEXT_BUILDER,
)
from travel_agent.planning.requirements.amendments import intent_amendment_router_node
from travel_agent.planning.requirements.approval import (
    plan_gate_node,
    route_after_plan_gate,
)
from travel_agent.planning.requirements.entry import clarifier_node
from travel_agent.planning.requirements.natural_language import prepare_requirements_node
from travel_agent.planning.requirements.understanding import (
    understanding_agent_node,
    understanding_gate_node,
)
from travel_agent.planning.requirements.summary import (
    trip_summary_card_after_brief_node,
)
from travel_agent.planning.research.accommodation.node import (
    accommodation_researcher_node,
)
from travel_agent.planning.research.destination.node import destination_researcher_node
from travel_agent.planning.research.dispatch import (
    dispatcher_node,
    route_after_dispatcher,
)
from travel_agent.planning.research.plan import planner_node
from travel_agent.planning.research.research_plan_node import research_plan_generator_node
from travel_agent.planning.research.transport.node import transport_researcher_node
from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.weather.node import (
    destination_geo_resolver_node,
    weather_context_builder_node,
    weather_research_authorized,
)

logger = logging.getLogger(__name__)


def _route_after_research_plan_generation(state: TravelAgentState) -> str:
    if state.pending_intent_amendments:
        return NODE_INTENT_AMENDMENT_ROUTER
    if state.research_plan_error:
        return NODE_PLAN_GATE
    return NODE_MINIMUM_DELIVERY_DRAFT


def _route_after_boundary(next_node: str):
    def route(state: TravelAgentState) -> str:
        if state.pending_intent_amendments:
            return NODE_INTENT_AMENDMENT_ROUTER
        return next_node

    return route


def _route_after_weather(state: TravelAgentState) -> str:
    if state.pending_intent_amendments:
        return NODE_INTENT_AMENDMENT_ROUTER
    # 旧 checkpoint 可能把未审批的天气节点作为下一步；回到计划准备。
    if not weather_research_authorized(state):
        return NODE_SUMMARY_CARD_BRIEF
    return NODE_DISPATCHER


def _route_after_dispatcher_with_amendments(state: TravelAgentState):
    if state.pending_intent_amendments:
        return NODE_INTENT_AMENDMENT_ROUTER
    return route_after_dispatcher(state)


def _route_after_itinerary(state: TravelAgentState) -> str:
    """组合后的出口：返研请求路由到对应 Worker，其余回 dispatcher。"""
    if state.pending_intent_amendments:
        return NODE_INTENT_AMENDMENT_ROUTER
    target = state.next_agent
    if target in (NODE_DESTINATION, NODE_TRANSPORT, NODE_ACCOMMODATION):
        return target
    return NODE_DISPATCHER


def _route_after_understanding(state: TravelAgentState) -> str:
    if state.pending_intent_amendments:
        return NODE_INTENT_AMENDMENT_ROUTER
    if state.understanding_pending_questions:
        return NODE_UNDERSTANDING_GATE
    return NODE_REQUIREMENTS_PREPARER


def route_after_intent_amendment(state: TravelAgentState) -> str:
    route = str(state.intent_amendment_route or "")
    if not route:
        raise RuntimeError("intent amendment router produced no continuation")
    return route


def build_travel_workflow() -> StateGraph:
    """构建深度调研工作流图（三层架构）。"""
    graph = StateGraph(TravelAgentState)

    from travel_agent.planning.recovery import with_worker_recovery

    graph.add_node(NODE_CLARIFIER, with_run_control(NODE_CLARIFIER, clarifier_node))
    graph.add_node(
        NODE_UNDERSTANDING_AGENT,
        with_run_control(
            NODE_UNDERSTANDING_AGENT,
            with_worker_recovery(NODE_UNDERSTANDING_AGENT, understanding_agent_node),
        ),
    )
    graph.add_node(
        NODE_UNDERSTANDING_GATE,
        with_run_control(NODE_UNDERSTANDING_GATE, understanding_gate_node),
    )
    graph.add_node(
        NODE_REQUIREMENTS_PREPARER,
        with_run_control(
            NODE_REQUIREMENTS_PREPARER, prepare_requirements_node
        ),
    )
    graph.add_node(
        NODE_RESEARCH_PLAN_GENERATOR,
        with_run_control(NODE_RESEARCH_PLAN_GENERATOR, research_plan_generator_node),
    )
    graph.add_node(
        NODE_INTENT_AMENDMENT_ROUTER,
        with_run_control(NODE_INTENT_AMENDMENT_ROUTER, intent_amendment_router_node),
    )
    graph.add_node(
        NODE_MINIMUM_DELIVERY_DRAFT,
        with_run_control(
            NODE_MINIMUM_DELIVERY_DRAFT, minimum_delivery_draft_builder_node
        ),
    )
    graph.add_node(
        NODE_DESTINATION_GEO_RESOLVER,
        with_run_control(NODE_DESTINATION_GEO_RESOLVER, destination_geo_resolver_node),
    )
    graph.add_node(
        NODE_WEATHER_CONTEXT_BUILDER,
        with_run_control(NODE_WEATHER_CONTEXT_BUILDER, weather_context_builder_node),
    )
    graph.add_node(
        NODE_SUMMARY_CARD_BRIEF,
        with_run_control(NODE_SUMMARY_CARD_BRIEF, trip_summary_card_after_brief_node),
    )
    graph.add_node(NODE_PLANNER, with_run_control(NODE_PLANNER, planner_node))
    graph.add_node(NODE_PLAN_GATE, with_run_control(NODE_PLAN_GATE, plan_gate_node))

    graph.add_node(NODE_DISPATCHER, with_run_control(NODE_DISPATCHER, dispatcher_node))
    graph.add_node(
        NODE_DESTINATION,
        with_run_control(
            NODE_DESTINATION,
            with_worker_recovery(NODE_DESTINATION, destination_researcher_node),
        ),
    )
    graph.add_node(
        NODE_TRANSPORT,
        with_run_control(
            NODE_TRANSPORT,
            with_worker_recovery(NODE_TRANSPORT, transport_researcher_node),
        ),
    )
    graph.add_node(
        NODE_ACCOMMODATION,
        with_run_control(
            NODE_ACCOMMODATION,
            with_worker_recovery(NODE_ACCOMMODATION, accommodation_researcher_node),
        ),
    )
    graph.add_node(
        NODE_ITINERARY, with_run_control(NODE_ITINERARY, itinerary_planner_node)
    )
    graph.add_node(
        NODE_BUDGET_ESTIMATE,
        with_run_control(NODE_BUDGET_ESTIMATE, budget_estimate_node),
    )
    graph.add_node(
        NODE_DELIVERY_PROJECTOR,
        with_run_control(NODE_DELIVERY_PROJECTOR, delivery_projection_node),
    )
    graph.add_node(
        NODE_DELIVERY_FINALIZER,
        with_run_control(NODE_DELIVERY_FINALIZER, delivery_finalizer_node),
    )

    graph.add_edge(START, NODE_CLARIFIER)
    graph.add_edge(NODE_CLARIFIER, NODE_UNDERSTANDING_AGENT)
    graph.add_conditional_edges(
        NODE_UNDERSTANDING_AGENT,
        _route_after_understanding,
        {
            NODE_INTENT_AMENDMENT_ROUTER: NODE_INTENT_AMENDMENT_ROUTER,
            NODE_UNDERSTANDING_GATE: NODE_UNDERSTANDING_GATE,
            NODE_REQUIREMENTS_PREPARER: NODE_REQUIREMENTS_PREPARER,
        },
    )
    graph.add_edge(NODE_UNDERSTANDING_GATE, NODE_UNDERSTANDING_AGENT)
    graph.add_conditional_edges(
        NODE_REQUIREMENTS_PREPARER,
        _route_after_boundary(NODE_RESEARCH_PLAN_GENERATOR),
        {
            NODE_INTENT_AMENDMENT_ROUTER: NODE_INTENT_AMENDMENT_ROUTER,
            NODE_RESEARCH_PLAN_GENERATOR: NODE_RESEARCH_PLAN_GENERATOR,
        },
    )
    graph.add_conditional_edges(
        NODE_RESEARCH_PLAN_GENERATOR,
        _route_after_research_plan_generation,
        {
            NODE_INTENT_AMENDMENT_ROUTER: NODE_INTENT_AMENDMENT_ROUTER,
            NODE_PLAN_GATE: NODE_PLAN_GATE,
            NODE_MINIMUM_DELIVERY_DRAFT: NODE_MINIMUM_DELIVERY_DRAFT,
        },
    )
    for source, target in (
        (NODE_MINIMUM_DELIVERY_DRAFT, NODE_DESTINATION_GEO_RESOLVER),
        (NODE_DESTINATION_GEO_RESOLVER, NODE_SUMMARY_CARD_BRIEF),
        (NODE_SUMMARY_CARD_BRIEF, NODE_PLANNER),
        (NODE_PLANNER, NODE_PLAN_GATE),
        (NODE_BUDGET_ESTIMATE, NODE_DELIVERY_PROJECTOR),
        (NODE_DELIVERY_PROJECTOR, NODE_DELIVERY_FINALIZER),
    ):
        graph.add_conditional_edges(
            source,
            _route_after_boundary(target),
            {
                NODE_INTENT_AMENDMENT_ROUTER: NODE_INTENT_AMENDMENT_ROUTER,
                target: target,
            },
        )

    graph.add_conditional_edges(
        NODE_WEATHER_CONTEXT_BUILDER,
        _route_after_weather,
        {
            NODE_INTENT_AMENDMENT_ROUTER: NODE_INTENT_AMENDMENT_ROUTER,
            NODE_SUMMARY_CARD_BRIEF: NODE_SUMMARY_CARD_BRIEF,
            NODE_DISPATCHER: NODE_DISPATCHER,
        },
    )

    graph.add_conditional_edges(
        NODE_DELIVERY_FINALIZER,
        _route_after_boundary(END),
        {
            NODE_INTENT_AMENDMENT_ROUTER: NODE_INTENT_AMENDMENT_ROUTER,
            END: END,
        },
    )

    for worker in (NODE_DESTINATION, NODE_TRANSPORT, NODE_ACCOMMODATION):
        graph.add_conditional_edges(
            worker,
            _route_after_boundary(NODE_DISPATCHER),
            {
                NODE_INTENT_AMENDMENT_ROUTER: NODE_INTENT_AMENDMENT_ROUTER,
                NODE_DISPATCHER: NODE_DISPATCHER,
            },
        )
    graph.add_conditional_edges(
        NODE_ITINERARY,
        _route_after_itinerary,
        {
            NODE_INTENT_AMENDMENT_ROUTER: NODE_INTENT_AMENDMENT_ROUTER,
            NODE_DISPATCHER: NODE_DISPATCHER,
            NODE_DESTINATION: NODE_DESTINATION,
            NODE_TRANSPORT: NODE_TRANSPORT,
            NODE_ACCOMMODATION: NODE_ACCOMMODATION,
        },
    )

    graph.add_conditional_edges(
        NODE_PLAN_GATE,
        route_after_plan_gate,
        {
            NODE_REQUIREMENTS_PREPARER: NODE_REQUIREMENTS_PREPARER,
            NODE_INTENT_AMENDMENT_ROUTER: NODE_INTENT_AMENDMENT_ROUTER,
            NODE_RESEARCH_PLAN_GENERATOR: NODE_RESEARCH_PLAN_GENERATOR,
            # The gate seals authorization before any external weather request.
            NODE_DISPATCHER: NODE_WEATHER_CONTEXT_BUILDER,
        },
    )

    amendment_continuations = {
        NODE_UNDERSTANDING_AGENT,
        NODE_REQUIREMENTS_PREPARER,
        NODE_RESEARCH_PLAN_GENERATOR,
        NODE_MINIMUM_DELIVERY_DRAFT,
        NODE_DESTINATION_GEO_RESOLVER,
        NODE_WEATHER_CONTEXT_BUILDER,
        NODE_SUMMARY_CARD_BRIEF,
        NODE_PLANNER,
        NODE_PLAN_GATE,
        NODE_DISPATCHER,
        NODE_DESTINATION,
        NODE_TRANSPORT,
        NODE_ACCOMMODATION,
        NODE_ITINERARY,
        NODE_BUDGET_ESTIMATE,
        NODE_DELIVERY_PROJECTOR,
        NODE_DELIVERY_FINALIZER,
    }
    graph.add_conditional_edges(
        NODE_INTENT_AMENDMENT_ROUTER,
        route_after_intent_amendment,
        {node: node for node in amendment_continuations},
    )

    graph.add_conditional_edges(
        NODE_DISPATCHER,
        _route_after_dispatcher_with_amendments,
        {
            NODE_INTENT_AMENDMENT_ROUTER: NODE_INTENT_AMENDMENT_ROUTER,
            "to_check": NODE_BUDGET_ESTIMATE,
            NODE_DESTINATION: NODE_DESTINATION,
            NODE_TRANSPORT: NODE_TRANSPORT,
            NODE_ACCOMMODATION: NODE_ACCOMMODATION,
            NODE_ITINERARY: NODE_ITINERARY,
        },
    )

    return graph


_compiled_graph = None


_compiled_graphs_with_checkpointer: Dict[int, Any] = {}


def get_travel_graph(checkpointer: Optional[Any] = None):
    """获取编译后的深度调研工作流图（单例）。"""
    global _compiled_graph
    if checkpointer is None:
        if _compiled_graph is None:
            workflow = build_travel_workflow()
            _compiled_graph = workflow.compile()
            logger.info("LangGraph 深度调研工作流编译完成（无 checkpointer）")
        return _compiled_graph

    cache_key = id(checkpointer)
    if cache_key not in _compiled_graphs_with_checkpointer:
        workflow = build_travel_workflow()
        _compiled_graphs_with_checkpointer[cache_key] = workflow.compile(
            checkpointer=checkpointer
        )
        logger.info("LangGraph 深度调研工作流编译完成（Postgres checkpointer）")
    return _compiled_graphs_with_checkpointer[cache_key]
