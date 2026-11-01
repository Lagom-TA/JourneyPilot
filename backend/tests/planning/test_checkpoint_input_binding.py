"""检查点只在输入一致且可由当前规划图恢复时继续。"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.workflow import CheckpointContractError, TravelPlanningWorkflow


async def test_checkpoint_input_probe_binds_run_session_identity_and_original_text():
    builder = StateGraph(TravelAgentState)
    builder.add_node("offline_noop", lambda _state: {})
    builder.add_edge(START, "offline_noop")
    builder.add_edge("offline_noop", END)
    saver = InMemorySaver()
    graph = builder.compile(checkpointer=saver)
    identity = {"origin": {"name": "上海"}, "destinations": [{"name": "杭州"}]}
    await graph.ainvoke(
        TravelAgentState(run_id="offline-run", session_id="offline-session", user_id="local", user_query="不吃牛肉", controlled_trip_identity=identity),
        {"configurable": {"thread_id": "offline-run"}},
    )
    workflow = object.__new__(TravelPlanningWorkflow)
    workflow._checkpointer = saver
    workflow._graph = graph
    ok, checkpoint_id = await workflow.probe_checkpoint_input(
        "offline-run", session_id="offline-session", user_message="不吃牛肉", controlled_trip_identity=identity, intake_evidence_sources=[],
    )
    assert ok and checkpoint_id
    wrong_text, _ = await workflow.probe_checkpoint_input(
        "offline-run", session_id="offline-session", user_message="吃牛肉", controlled_trip_identity=identity, intake_evidence_sources=[],
    )
    wrong_session, _ = await workflow.probe_checkpoint_input(
        "offline-run", session_id="another-session", user_message="不吃牛肉", controlled_trip_identity=identity, intake_evidence_sources=[],
    )
    wrong_identity, _ = await workflow.probe_checkpoint_input(
        "offline-run", session_id="offline-session", user_message="不吃牛肉", controlled_trip_identity={"destinations": [{"name": "东京"}]}, intake_evidence_sources=[],
    )
    wrong_evidence, _ = await workflow.probe_checkpoint_input(
        "offline-run", session_id="offline-session", user_message="不吃牛肉", controlled_trip_identity=identity,
        intake_evidence_sources=[{"kind": "current_request", "text": "吃牛肉"}],
    )
    assert not wrong_text and not wrong_session and not wrong_identity and not wrong_evidence


@pytest.mark.parametrize("pending", ["request_contract_normalizer", "plan_gate"])
async def test_old_checkpoint_is_rejected_before_resumption(pending):
    from langgraph.types import interrupt
    from travel_agent.planning.graph import build_travel_workflow

    builder = StateGraph(dict)
    builder.add_node(pending, lambda state: interrupt({"old": "plan"}))
    builder.add_edge(START, pending)
    builder.add_edge(pending, END)
    saver = InMemorySaver()
    await builder.compile(checkpointer=saver).ainvoke(
        {"run_id": "offline-run", "user_query": "喜欢园林"},
        {"configurable": {"thread_id": "offline-run"}},
    )
    workflow = object.__new__(TravelPlanningWorkflow)
    workflow._checkpointer = saver
    workflow._graph = build_travel_workflow().compile(checkpointer=saver)
    with pytest.raises(CheckpointContractError, match="重新规划"):
        await workflow.probe_checkpoint("offline-run")
