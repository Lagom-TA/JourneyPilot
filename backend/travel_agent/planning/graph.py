"""规划工作流图。"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import langchain
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
    NODE_REQUEST_CONTRACT_NORMALIZER,
    NODE_RESEARCH_BRIEF_BUILDER,
    NODE_SUMMARY_CARD_BRIEF,
    NODE_TRANSPORT,
    NODE_WEATHER_CONTEXT_BUILDER,
)
from travel_agent.planning.requirements.amendments import intent_amendment_router_node
from travel_agent.planning.requirements.approval import (
    plan_gate_node,
    route_after_plan_gate,
)
from travel_agent.planning.requirements.entry import clarifier_node
from travel_agent.planning.requirements.normalization.node import (
    request_contract_normalizer_node,
)
from travel_agent.planning.requirements.summary import (
    trip_summary_card_after_brief_node,
)
from travel_agent.planning.research.accommodation.node import (
    accommodation_researcher_node,
)
from travel_agent.planning.research.brief_node import research_brief_builder_node
from travel_agent.planning.research.destination.node import destination_researcher_node
from travel_agent.planning.research.dispatch import (
    dispatcher_node,
    route_after_dispatcher,
)
from travel_agent.planning.research.plan import planner_node
from travel_agent.planning.research.transport.node import transport_researcher_node
from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.weather.node import (
    destination_geo_resolver_node,
    weather_context_builder_node,
)

logger = logging.getLogger(__name__)


# 较新的 LangChain 不再提供该属性，LangGraph 仍会读取它。
if not hasattr(langchain, "debug"):
    langchain.debug = False


def route_after_destination(state: TravelAgentState) -> str:
    """destination_researcher 节点后的路由：触发 ask_user 则中断，否则回 dispatcher。"""
    if state.pending_intent_amendments:
        return NODE_INTENT_AMENDMENT_ROUTER
    if state.next_agent == "HALT":
        return "HALT"
    return "dispatcher"


def _route_after_boundary(next_node: str):
    def route(state: TravelAgentState) -> str:
        if state.pending_intent_amendments:
            return NODE_INTENT_AMENDMENT_ROUTER
        return next_node

    return route


def _route_after_dispatcher_with_amendments(state: TravelAgentState):
    if state.pending_intent_amendments:
        return NODE_INTENT_AMENDMENT_ROUTER
    return route_after_dispatcher(state)


def route_after_intent_amendment(state: TravelAgentState) -> str:
    route = str(state.intent_amendment_route or "")
    if not route:
        raise RuntimeError("intent amendment router produced no continuation")
    return route


def build_travel_workflow() -> StateGraph:
    """构建深度调研工作流图（三层架构）。"""
    graph = StateGraph(TravelAgentState)

    graph.add_node(NODE_CLARIFIER, with_run_control(NODE_CLARIFIER, clarifier_node))
    graph.add_node(
        NODE_REQUEST_CONTRACT_NORMALIZER,
        with_run_control(
            NODE_REQUEST_CONTRACT_NORMALIZER, request_contract_normalizer_node
        ),
    )
    graph.add_node(
        NODE_RESEARCH_BRIEF_BUILDER,
        with_run_control(NODE_RESEARCH_BRIEF_BUILDER, research_brief_builder_node),
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
    from travel_agent.planning.recovery import with_worker_recovery

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
    graph.add_edge(NODE_REQUEST_CONTRACT_NORMALIZER, NODE_RESEARCH_BRIEF_BUILDER)
    for source, target in (
        (NODE_RESEARCH_BRIEF_BUILDER, NODE_MINIMUM_DELIVERY_DRAFT),
        (NODE_MINIMUM_DELIVERY_DRAFT, NODE_DESTINATION_GEO_RESOLVER),
        (NODE_DESTINATION_GEO_RESOLVER, NODE_WEATHER_CONTEXT_BUILDER),
        (NODE_WEATHER_CONTEXT_BUILDER, NODE_SUMMARY_CARD_BRIEF),
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
        NODE_DELIVERY_FINALIZER,
        _route_after_boundary(END),
        {
            NODE_INTENT_AMENDMENT_ROUTER: NODE_INTENT_AMENDMENT_ROUTER,
            END: END,
        },
    )

    graph.add_conditional_edges(
        NODE_DESTINATION,
        route_after_destination,
        {
            "HALT": END,
            "dispatcher": NODE_DISPATCHER,
            NODE_INTENT_AMENDMENT_ROUTER: NODE_INTENT_AMENDMENT_ROUTER,
        },
    )
    for worker in (NODE_TRANSPORT, NODE_ACCOMMODATION, NODE_ITINERARY):
        graph.add_conditional_edges(
            worker,
            _route_after_boundary(NODE_DISPATCHER),
            {
                NODE_INTENT_AMENDMENT_ROUTER: NODE_INTENT_AMENDMENT_ROUTER,
                NODE_DISPATCHER: NODE_DISPATCHER,
            },
        )

    graph.add_edge(NODE_CLARIFIER, NODE_REQUEST_CONTRACT_NORMALIZER)

    graph.add_conditional_edges(
        NODE_PLAN_GATE,
        route_after_plan_gate,
        {
            NODE_REQUEST_CONTRACT_NORMALIZER: NODE_REQUEST_CONTRACT_NORMALIZER,
            NODE_INTENT_AMENDMENT_ROUTER: NODE_INTENT_AMENDMENT_ROUTER,
            NODE_DISPATCHER: NODE_DISPATCHER,
        },
    )

    amendment_continuations = {
        NODE_REQUEST_CONTRACT_NORMALIZER,
        NODE_RESEARCH_BRIEF_BUILDER,
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
