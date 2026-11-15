"""研究方案的公开摘要、内部任务与检查点恢复契约。"""

from __future__ import annotations

import hashlib
import json
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from tests.fixtures.planning_state import make_planning_state
from tests.support.memory_stores import InMemoryWorkerJournalStore
from travel_agent.api.presenters.runs import _event_response, _state_response
from travel_agent.api.sse_projection import project_sse_payload
from travel_agent.planning.itinerary.prompts import _build_composition_prompt
from travel_agent.planning.recovery import invocation_scope, with_worker_recovery
from travel_agent.planning.requirements.approval import _build_plan_gate_payload, plan_gate_node
from travel_agent.planning.requirements.natural_language import ResearchPlan
from travel_agent.planning.research import research_plan_node
from travel_agent.planning.research.plan import planner_node
from travel_agent.planning.research.prompts import build_research_packet_prompt
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.run_contracts import TripRunEvent, TripRunState, TripRunStatus


SUMMARY = "- 探索园林\n- 查找适合慢游的交通"
GUIDANCE = "内部研究重点：园林体验优先，交通尽量减少步行。"
REQUIREMENTS = "必须少走路、每天最多两个景点，午餐避免花生。"
WORKERS = ("destination_researcher", "transport_researcher", "accommodation_researcher")
ROLES = (*WORKERS, "itinerary_planner")
GROUPS = [["destination_researcher"], ["transport_researcher", "accommodation_researcher"], ["itinerary_planner"]]


def _state(plan: dict | None = None) -> TravelAgentState:
    return make_planning_state().model_copy(update={
        "current_requirements": REQUIREMENTS,
        "research_plan": ResearchPlan.model_validate(plan) if plan is not None else None,
        "agent_assignments": {},
    })


def _gate_graph():
    builder = StateGraph(TravelAgentState)
    builder.add_node("plan_gate", plan_gate_node)
    builder.add_edge(START, "plan_gate")
    builder.add_edge("plan_gate", END)
    return builder.compile(checkpointer=InMemorySaver())


@pytest.mark.parametrize(
    "invalid",
    [
        {"agent_guidance": GUIDANCE},
        {"summary": "", "agent_guidance": GUIDANCE},
        {"summary": "  \n ", "agent_guidance": GUIDANCE},
        {"summary": None, "agent_guidance": GUIDANCE},
        {"summary": SUMMARY},
        {"summary": SUMMARY, "agent_guidance": ""},
        {"summary": SUMMARY, "agent_guidance": "  \n "},
        {"summary": SUMMARY, "agent_guidance": None},
    ],
    ids=["missing-summary", "empty-summary", "blank-summary", "null-summary", "missing-guidance", "empty-guidance", "blank-guidance", "null-guidance"],
)
async def test_invalid_generated_field_cannot_be_approved_and_retry_succeeds(invalid, monkeypatch):
    replies = iter([invalid, {"summary": SUMMARY, "agent_guidance": GUIDANCE}])
    requests = []

    class Model:
        async def ainvoke(self, messages, **kwargs):
            requests.append(messages)
            return json.dumps(next(replies), ensure_ascii=False)

    monkeypatch.setattr(research_plan_node, "get_model_router", lambda: object())
    monkeypatch.setattr(research_plan_node, "llm_for_task", lambda *args, **kwargs: Model())
    builder = StateGraph(TravelAgentState)
    builder.add_node("research_plan_generator", research_plan_node.research_plan_generator_node)
    builder.add_node("plan_gate", plan_gate_node)
    builder.add_edge(START, "research_plan_generator")
    builder.add_edge("research_plan_generator", "plan_gate")
    builder.add_conditional_edges(
        "plan_gate", lambda state: state.plan_gate_decision["action"],
        {"retry": "research_plan_generator", "approve": END},
    )
    graph = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "retry-invalid", "plan_gate_enabled": True}}

    result = await graph.ainvoke(_state(), config)
    failed = result["__interrupt__"][0].value
    snapshot = await graph.aget_state(config)
    assert snapshot.values["research_plan"] is None
    assert snapshot.values["research_plan_error"]["code"] == "research_plan_unavailable"
    assert "retry" in failed["decision_options"]
    assert "approve" not in failed["decision_options"]
    rejected = await graph.ainvoke(Command(resume={"action": "approve", "approval_token": failed["approval_token"]}), config)
    assert rejected["__interrupt__"][0].value == failed
    retried = await graph.ainvoke(Command(resume={"action": "retry", "approval_token": failed["approval_token"]}), config)
    current = retried["__interrupt__"][0].value
    assert len(requests) == 2
    assert current["plan_text"] == SUMMARY
    assert "approve" in current["decision_options"]
    assert current["approval_token"] != failed["approval_token"]
    stale = await graph.ainvoke(Command(resume={"action": "approve", "approval_token": failed["approval_token"]}), config)
    assert stale["__interrupt__"][0].value == current
    approved = await graph.ainvoke(Command(resume={"action": "approve", "approval_token": current["approval_token"]}), config)
    assert approved["research_plan"].agent_guidance == GUIDANCE
    assert approved["research_plan_error"] is None
    assert approved["minimum_delivery_draft"].planning_authorized


async def test_generator_prompts_for_clear_concise_actionable_summary_without_disclaimers(monkeypatch):
    captured = []

    class Model:
        async def ainvoke(self, messages, **kwargs):
            captured.extend(messages)
            return {"summary": SUMMARY, "agent_guidance": GUIDANCE}

    monkeypatch.setattr(research_plan_node, "get_model_router", lambda: object())
    monkeypatch.setattr(research_plan_node, "llm_for_task", lambda *args, **kwargs: Model())
    generated = await research_plan_node.research_plan_generator_node(_state())
    system = captured[0]["content"]
    assert generated["research_plan"].agent_guidance == GUIDANCE
    assert generated["research_plan_error"] is None
    assert "summary" in system and "agent_guidance" in system
    assert "旅行者" in system and "研究" in system and "角色" in system
    assert any(word in system for word in ("简短", "简洁", "精简"))
    assert any(word in system for word in ("具体", "行动"))
    assert any(word in system for word in ("不写", "避免", "不要"))
    assert any(word in system for word in ("免责声明", "推脱", "甩锅", "不粘锅"))
    assert REQUIREMENTS in captured[-1]["content"]


@pytest.mark.parametrize("legacy", [False, True], ids=["new", "legacy-checkpoint"])
async def test_planner_dispatches_correct_task_and_keeps_complete_requirements(legacy):
    plan = {"summary": SUMMARY} if legacy else {"summary": SUMMARY, "agent_guidance": GUIDANCE}
    state = _state(plan)
    update = await planner_node(state)
    expected = SUMMARY if legacy else GUIDANCE
    assert update["execution_plan"] == GROUPS
    assert set(update["agent_assignments"]) == set(ROLES)
    assert all(update["agent_assignments"][role]["objective"] == expected for role in ROLES)
    state = state.model_copy(update=update)
    for worker in WORKERS:
        prompt = build_research_packet_prompt(
            worker_kind=worker, run_id=state.run_id, task_id=worker,
            fact_data_revision=state.fact_data_revision, current_time="now",
            candidate_limit=4, task_desc=state.agent_assignments[worker]["objective"], state=state,
        )
        shared_facts = json.loads(prompt.runtime.splitlines()[1])
        assert shared_facts["研究指引"] == expected
        assert shared_facts["整理后的旅行要求"] == REQUIREMENTS
        if not legacy:
            assert SUMMARY not in json.dumps(shared_facts, ensure_ascii=False)
    prompt = _build_composition_prompt(state, state.agent_assignments["itinerary_planner"]["objective"])
    assert expected in prompt.runtime
    assert REQUIREMENTS in prompt.runtime
    if not legacy:
        assert SUMMARY not in prompt.runtime


async def test_public_gate_and_sse_and_restored_state_never_expose_guidance():
    state = _state({"summary": SUMMARY, "agent_guidance": GUIDANCE})
    graph = _gate_graph()
    config = {"configurable": {"thread_id": "projection", "plan_gate_enabled": True}}
    result = await graph.ainvoke(state, config)
    gate = result["__interrupt__"][0].value
    assert gate["plan_text"] == SUMMARY
    assert [step["agents"] for step in gate["plan"]["steps"]] == GROUPS
    assert all(task == SUMMARY for step in gate["plan"]["steps"] for task in step["tasks"].values())
    assert GUIDANCE not in json.dumps(gate, ensure_ascii=False)

    # 显式加入内部字段，验证实时帧与持久恢复均按公开字段投影。
    stored = {**gate, "agent_guidance": GUIDANCE}
    live = project_sse_payload({"type": "approval_gate_raised", "gate": "plan", "payload": stored})
    restored = _state_response(TripRunState(
        run_id=state.run_id, status=TripRunStatus.AWAITING_INPUT,
        pending_user_choice={"type": "approval_gate", "gate": "plan", "payload": stored},
    )).model_dump(mode="json")
    recovered = restored["pending_user_choice"]
    assert live["payload"] == recovered["payload"] == gate
    # 事件窗口回放同样只带公开方案，供刷新后的阶段回看使用。
    replayed = _event_response(TripRunEvent(
        run_id=state.run_id, sequence=1, event_type="run.gate_raised",
        payload={"gate": "plan", "payload": stored},
    )).model_dump(mode="json")
    assert replayed["payload"]["gate"] == "plan"
    assert replayed["payload"]["payload"] == gate
    assert GUIDANCE not in json.dumps(live, ensure_ascii=False)
    assert GUIDANCE not in json.dumps(restored, ensure_ascii=False)
    assert GUIDANCE not in json.dumps(replayed, ensure_ascii=False)


async def test_token_changes_for_internal_guidance_and_rejects_old_approval():
    first = _state({"summary": SUMMARY, "agent_guidance": GUIDANCE})
    second = _state({"summary": SUMMARY, "agent_guidance": "内部研究重点：优先公共交通。"})
    old_gate = _build_plan_gate_payload(first)
    new_gate = _build_plan_gate_payload(second)
    assert old_gate["plan"] == new_gate["plan"]
    assert old_gate["plan_text"] == new_gate["plan_text"] == SUMMARY
    assert old_gate["approval_token"] != new_gate["approval_token"]
    assert old_gate["approval_token"] == _build_plan_gate_payload(first)["approval_token"]
    graph = _gate_graph()
    config = {"configurable": {"thread_id": "changed-guidance", "plan_gate_enabled": True}}
    current = (await graph.ainvoke(second, config))["__interrupt__"][0].value
    rejected = await graph.ainvoke(Command(resume={"action": "approve", "approval_token": old_gate["approval_token"]}), config)
    assert rejected["__interrupt__"][0].value == current
    accepted = await graph.ainvoke(Command(resume={"action": "approve", "approval_token": new_gate["approval_token"]}), config)
    assert accepted["minimum_delivery_draft"].planning_authorized


@pytest.mark.parametrize("plan", [{"summary": SUMMARY}, {"summary": SUMMARY, "agent_guidance": GUIDANCE}])
async def test_gate_rejects_assignments_that_do_not_match_the_plan(plan):
    state = _state(plan)
    state = state.model_copy(update=await planner_node(state))
    assignments = dict(state.agent_assignments)
    assignments["destination_researcher"] = {
        **assignments["destination_researcher"], "objective": "另一份研究任务",
    }
    state = state.model_copy(update={"agent_assignments": assignments})
    graph = _gate_graph()
    config = {"configurable": {"thread_id": "mismatched-assignment", "plan_gate_enabled": True}}
    gate = (await graph.ainvoke(state, config))["__interrupt__"][0].value
    with pytest.raises(ValueError, match="研究任务与当前方案不一致"):
        await graph.ainvoke(Command(resume={"action": "approve", "approval_token": gate["approval_token"]}), config)


async def test_legacy_summary_checkpoint_keeps_original_token_and_execution():
    state = _state({"summary": SUMMARY})
    legacy_steps = [
        {"step": index, "agents": group, "tasks": {role: SUMMARY for role in group}}
        for index, group in enumerate(GROUPS, 1)
    ]
    material = {
        "run_id": state.run_id,
        "generation_id": state.planning_generation.generation_id,
        "revision": state.plan_gate_revision_count,
        "plan": {"steps": legacy_steps},
        "plan_text": SUMMARY,
    }
    digest = hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    legacy_token = f"plan_gate.approval:{digest}"
    gate = _build_plan_gate_payload(state)
    assert gate["approval_token"] == legacy_token
    assert gate["plan"]["steps"] == legacy_steps
    assert _build_plan_gate_payload(_state({"summary": SUMMARY, "agent_guidance": None}))["approval_token"] == legacy_token
    assert _build_plan_gate_payload(_state({"summary": SUMMARY, "agent_guidance": SUMMARY}))["approval_token"] != legacy_token
    graph = _gate_graph()
    config = {"configurable": {"thread_id": "legacy-token", "plan_gate_enabled": True}}
    interrupted = await graph.ainvoke(state, config)
    assert interrupted["__interrupt__"][0].value["approval_token"] == legacy_token
    approved = await graph.ainvoke(Command(resume={"action": "approve", "approval_token": legacy_token}), config)
    assert approved["minimum_delivery_draft"].planning_authorized
    update = await planner_node(TravelAgentState.model_validate(approved))
    assert update["execution_plan"] == GROUPS
    assert all(update["agent_assignments"][role]["objective"] == SUMMARY for role in ROLES)


async def test_legacy_recovery_scope_and_journal_replay_keep_the_old_identity():
    node = "itinerary_planner"
    config = {"configurable": {"__pregel_task_id": "legacy-task"}}
    assignment = {"objective": "园林慢游"}
    state = TravelAgentState.model_validate({
        "run_id": "legacy-run", "user_query": "东京旅行", "current_requirements": "少走路",
        "research_plan": {"summary": "园林慢游"},
        "planning_generation": {"generation_id": "generation_legacy", "revision": 1},
        "agent_assignments": {node: assignment},
    })
    # 独立固定旧检查点的输入形状和默认值，避免以现有投影推导期望值。
    old_fields = {
        "run_id": "legacy-run", "user_query": "东京旅行", "controlled_trip_identity": {},
        "current_requirements": "少走路", "research_plan": {"summary": "园林慢游"},
        "planning_generation": {"generation_id": "generation_legacy", "revision": 1},
        "constraint_pack": {}, "fact_data_revision": 0, "session_anchor": None,
        "preset_context": "", "weather_context": None, "recommendation_catalog": None,
        "research_packets": {}, "messages": [], "understanding_messages": [],
        "understanding_qa": [], "understanding_rounds": 0, "understanding_pending_questions": None,
        "placement_skeleton": None, "trip_workspace": None, "composition_failure_context": None,
        "composition_reschedule_rounds": 0, "research_redo_requests": None, "research_redo_rounds": {},
        "assignment": [node, assignment], "plan_gate_decision": None, "graph_task_id": "legacy-task",
    }
    old_digest = hashlib.sha256(json.dumps(old_fields, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    old_scope = f"{node}:{old_digest}"
    assert invocation_scope(state, node, config) == old_scope
    explicit_null = state.model_copy(update={"research_plan": ResearchPlan(summary="园林慢游", agent_guidance=None)})
    assert invocation_scope(explicit_null, node, config) == old_scope
    changed = state.model_copy(update={"research_plan": ResearchPlan(summary="园林慢游", agent_guidance="内部指引")})
    assert invocation_scope(changed, node, config) != old_scope

    store = InMemoryWorkerJournalStore()
    await store.save(state.run_id, old_scope, 0, {"worker_result": {"result": "旧结果"}})
    calls = []

    async def worker(_state, _config):
        calls.append(True)
        return {"result": "新结果"}

    recovered = with_worker_recovery(node, worker)
    config["configurable"]["worker_journal_store"] = store
    assert await recovered(state, config) == {"result": "旧结果"}
    assert calls == []
    assert await recovered(changed, config) == {"result": "新结果"}
    assert calls == [True]
