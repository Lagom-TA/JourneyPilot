"""Conversation graph."""

from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from travel_agent.conversation.answer.node import fast_answer_node
from travel_agent.planning.execution import with_run_control
from travel_agent.planning.state import TravelAgentState

logger = logging.getLogger(__name__)


NODE_FAST_ANSWER = "fast_answer_agent"


def build_fast_workflow() -> StateGraph:
    """构建快速模式工作流图（fast_answer_agent → END）。"""
    graph = StateGraph(TravelAgentState)
    graph.add_node(
        NODE_FAST_ANSWER, with_run_control(NODE_FAST_ANSWER, fast_answer_node)
    )
    graph.add_edge(START, NODE_FAST_ANSWER)
    graph.add_edge(NODE_FAST_ANSWER, END)
    return graph


_compiled_fast_graph = None


def get_fast_graph():
    """获取编译后的快速模式工作流图（单例）"""
    global _compiled_fast_graph
    if _compiled_fast_graph is None:
        workflow = build_fast_workflow()
        _compiled_fast_graph = workflow.compile()
        logger.info("LangGraph 快速模式工作流编译完成（简化版）")
    return _compiled_fast_graph
