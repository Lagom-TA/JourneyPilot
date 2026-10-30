"""A checkpoint may replace intake only when it contains the same input."""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.workflow import TravelPlanningWorkflow
from travel_agent.planning.requirements.intent_contracts import canonical_json_hash
from travel_agent.planning.requirements.confirmation_contracts import (
    AssertionDecision, AssertionDecisionInput, AssertionMeaning, RequirementDomain,
    SourceEvidence, SourceKind, build_assertion_candidate, build_confirmation_challenge,
    build_confirmation_receipt,
)


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


async def test_semantic_ack_probe_requires_the_durable_matching_complete_receipt():
    identity = {"destinations": [{"name": "杭州"}]}
    source = SourceEvidence(source_id="s1", kind=SourceKind.CURRENT_REQUEST, text="不喝咖啡", revision=1)
    assertion = build_assertion_candidate(
        source=source, span_start=2, span_end=4, quote="咖啡",
        domain=RequirementDomain.FOOD, meaning=AssertionMeaning.EXCLUDE,
        allowed_decisions=[AssertionDecision.AVOID, AssertionDecision.UNKNOWN], object_label="咖啡",
    )
    challenge = build_confirmation_challenge(
        run_id="semantic-run", session_id="semantic-session", revision=1,
        identity_hash=canonical_json_hash(identity), policy_version="v1", candidate_contract_hash="b" * 64,
        sources=[source], assertions=[assertion],
    )
    receipt = build_confirmation_receipt(
        challenge=challenge, sources=[source], assertions=[assertion],
        decisions=[AssertionDecisionInput(assertion_id=assertion.assertion_id, decision=AssertionDecision.AVOID)],
        submitted_token=challenge.token, run_id="semantic-run", session_id="semantic-session",
        identity_hash=canonical_json_hash(identity), policy_version="v1",
    )
    builder = StateGraph(TravelAgentState)
    builder.add_node("offline_noop", lambda _state: {})
    builder.add_edge(START, "offline_noop")
    builder.add_edge("offline_noop", END)
    saver = InMemorySaver()
    graph = builder.compile(checkpointer=saver)
    await graph.ainvoke(TravelAgentState(
        run_id="semantic-run", session_id="semantic-session", user_id="local",
        controlled_trip_identity=identity, semantic_receipt=receipt, semantic_candidate_hash="b" * 64,
        plan_gate_decision={"action": "semantic_confirmed", "challenge_id": challenge.token, "approval_token": "gate-token"},
    ), {"configurable": {"thread_id": "semantic-run"}})
    workflow = object.__new__(TravelPlanningWorkflow)
    workflow._checkpointer, workflow._graph = saver, graph
    assert await workflow.probe_semantic_decision(
        "semantic-run", action="semantic_confirmed", challenge_id=challenge.token, approval_token="gate-token",
    )
    assert not await workflow.probe_semantic_decision(
        "semantic-run", action="semantic_confirmed", challenge_id=challenge.token, approval_token="stale-token",
    )
