from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Annotated, Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from tests.support.memory_stores import InMemoryWorkerJournalStore
from travel_agent.planning.nodes import NODE_UNDERSTANDING_AGENT, NODE_UNDERSTANDING_GATE
from travel_agent.planning.recovery import invocation_scope, with_worker_recovery
from travel_agent.planning.requirements.generation_contracts import PlanningGeneration
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.journal import WorkerJournal, current_worker_journal


class LegacyResearchPlan(BaseModel):
    summary: str


class LegacyState(BaseModel):
    """理解阶段旧 checkpoint 使用的字段和默认值。"""

    messages: Annotated[list[BaseMessage], add_messages] = Field(default_factory=list)
    run_id: str = ""
    user_query: str = ""
    controlled_trip_identity: dict[str, Any] = Field(default_factory=dict)
    current_requirements: str = ""
    research_plan: LegacyResearchPlan | None = None
    planning_generation: PlanningGeneration | None = None
    constraint_pack: dict[str, Any] = Field(default_factory=dict)
    fact_data_revision: int = 0
    session_anchor: dict[str, Any] | None = None
    preset_context: str = ""
    weather_context: Any = None
    recommendation_catalog: Any = None
    research_packets: dict[str, Any] = Field(default_factory=dict)
    understanding_messages: list[dict[str, Any]] = Field(default_factory=list)
    understanding_qa: list[dict[str, Any]] = Field(default_factory=list)
    understanding_rounds: int = 0
    understanding_pending_questions: list[dict[str, Any]] | None = None
    current_time: str = ""
    plan_gate_amendment: Any = None
    pending_intent_amendments: list[Any] = Field(default_factory=list)
    refinement_context: str = ""
    plan_gate_decision: dict[str, Any] | None = None
    agent_assignments: dict[str, Any] = Field(default_factory=dict)


# 独立保留旧版理解节点身份所覆盖的字段，不能从当前实现反推出旧 scope。
_LEGACY_UNDERSTANDING_FIELDS = {
    "run_id", "user_query", "controlled_trip_identity", "current_requirements",
    "research_plan", "planning_generation", "constraint_pack", "fact_data_revision",
    "session_anchor", "preset_context", "weather_context", "recommendation_catalog",
    "research_packets", "messages", "understanding_messages", "understanding_qa",
    "understanding_rounds", "understanding_pending_questions", "current_time",
    "plan_gate_amendment", "pending_intent_amendments", "refinement_context",
}


def legacy_understanding_scope(state: LegacyState, task_id: str) -> str:
    fields = state.model_dump(mode="json", include=_LEGACY_UNDERSTANDING_FIELDS)
    fields["plan_gate_decision"] = state.plan_gate_decision
    fields["graph_task_id"] = task_id
    digest = hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return f"{NODE_UNDERSTANDING_AGENT}:{digest}"


class RecordingJournalStore(InMemoryWorkerJournalStore):
    def __init__(self):
        super().__init__()
        self.loads = []

    async def load(self, run_id, scope_id):
        version, payload = await super().load(run_id, scope_id)
        self.loads.append((run_id, scope_id, version))
        return version, payload


def _compile_understanding_graph(schema, saver, understanding, gate):
    graph = StateGraph(schema)
    graph.add_node(NODE_UNDERSTANDING_AGENT, understanding)
    graph.add_node(NODE_UNDERSTANDING_GATE, gate)
    graph.add_edge(START, NODE_UNDERSTANDING_AGENT)
    graph.add_conditional_edges(
        NODE_UNDERSTANDING_AGENT,
        lambda state: NODE_UNDERSTANDING_GATE if state.understanding_pending_questions is not None else END,
        {NODE_UNDERSTANDING_GATE: NODE_UNDERSTANDING_GATE, END: END},
    )
    graph.add_edge(NODE_UNDERSTANDING_GATE, NODE_UNDERSTANDING_AGENT)
    return graph.compile(checkpointer=saver)


async def test_old_checkpoint_replays_second_understanding_task_before_pending_write():
    saver = InMemorySaver()
    store = RecordingJournalStore()
    calls, task_ids, scopes, gate_calls = [], [], [], []
    before_crash = []
    question = {"id": "pace", "question": "希望什么节奏？", "kind": "single", "options": []}
    answer = {"question_id": "pace", "question": "希望什么节奏？", "answer": "慢一些"}
    first_update = {
        "messages": [AIMessage(content="请确认节奏", id="old-first")],
        "understanding_messages": [{"role": "assistant", "content": "希望什么节奏？"}],
        "understanding_qa": [],
        "understanding_rounds": 1,
        "understanding_pending_questions": [question],
        "controlled_trip_identity": {"party": {"adults": 2}},
        "current_requirements": "两人出游",
        "constraint_pack": {"pace": "待确认"},
    }
    second_update = {
        "messages": [AIMessage(content="已整理旅行需求", id="old-second")],
        "understanding_messages": [
            {"role": "assistant", "content": "希望什么节奏？"},
            {"role": "user", "content": "慢一些"},
            {"role": "assistant", "content": "确认慢游"},
        ],
        "understanding_qa": [answer],
        "understanding_rounds": 2,
        "understanding_pending_questions": None,
        "controlled_trip_identity": {"party": {"adults": 2}, "destinations": [{"name": "杭州"}]},
        "current_requirements": "两人到杭州慢游",
        "constraint_pack": {"pace": "慢游", "daily_attractions": 2},
    }

    async def legacy_understanding(state: LegacyState, config: RunnableConfig):
        assert "submitted_trip_identity" not in state.model_dump()
        task_id = config["configurable"]["__pregel_task_id"]
        task_ids.append(task_id)
        scope = legacy_understanding_scope(state, task_id)
        scopes.append(scope)
        calls.append(state.understanding_rounds)
        update = first_update if state.understanding_rounds == 0 else second_update
        version, payload = await store.load(state.run_id, scope)
        assert version == 0 and payload == {}
        journal = WorkerJournal(store, state.run_id, scope, version, payload, None)
        journal.payload["worker_result"] = deepcopy(update)
        await journal.commit()
        if state.understanding_rounds:
            before_crash.append(state.model_copy(deep=True))
            raise RuntimeError("crash after journal commit before pending write")
        return deepcopy(update)

    async def gate(state):
        gate_calls.append(state.understanding_rounds)
        assert state.understanding_pending_questions == [question]
        return {
            "understanding_messages": [*state.understanding_messages, {"role": "user", "content": "慢一些"}],
            "understanding_qa": [answer],
            "understanding_pending_questions": None,
        }

    legacy_graph = _compile_understanding_graph(LegacyState, saver, legacy_understanding, gate)
    config = {"configurable": {"thread_id": "old-understanding-run", "worker_journal_store": store}}
    initial = LegacyState(
        run_id="old-understanding-run",
        user_query="两个人去杭州",
        current_time="2026-11-09 10:00:00",
        session_anchor={"city": "上海"},
        preset_context="偏好自然景色",
        messages=[HumanMessage(content="两个人去杭州", id="old-user")],
    )
    assert "submitted_trip_identity" not in LegacyState.model_fields
    with pytest.raises(RuntimeError, match="after journal commit before pending write"):
        await legacy_graph.ainvoke(initial, config)

    assert calls == [0, 1]
    assert gate_calls == [1]
    assert len(set(task_ids)) == 2 and len(set(scopes)) == 2
    checkpoint = await saver.aget_tuple(config)
    assert checkpoint is not None
    assert "submitted_trip_identity" not in checkpoint.checkpoint["channel_values"]
    assert checkpoint.checkpoint["channel_values"]["understanding_qa"] == [answer]
    assert not any(
        task_id == task_ids[1] and channel in second_update
        for task_id, channel, _ in checkpoint.pending_writes
    )
    old_snapshot = await legacy_graph.aget_state(config)
    assert old_snapshot.next == (NODE_UNDERSTANDING_AGENT,)
    assert old_snapshot.tasks[0].id == task_ids[1]
    assert store.rows[(initial.run_id, scopes[0])][1]["worker_result"] == first_update
    assert store.rows[(initial.run_id, scopes[1])][1]["worker_result"] == second_update

    resumed_task_ids, resumed_states = [], []

    async def should_not_run(state: TravelAgentState, config: RunnableConfig):
        pytest.fail("恢复时不得再次执行已完成的理解 worker")

    recovered = with_worker_recovery(NODE_UNDERSTANDING_AGENT, should_not_run)

    async def current_understanding(state: TravelAgentState, config: RunnableConfig):
        resumed_task_ids.append(config["configurable"]["__pregel_task_id"])
        resumed_states.append(state.model_copy(deep=True))
        return await recovered(state, config)

    current_graph = _compile_understanding_graph(TravelAgentState, saver, current_understanding, gate)
    load_count = len(store.loads)
    result = await current_graph.ainvoke(None, config)

    assert resumed_task_ids == [task_ids[1]]
    assert resumed_states[0].submitted_trip_identity is None
    current_scope = invocation_scope(
        resumed_states[0], NODE_UNDERSTANDING_AGENT,
        {"configurable": {"__pregel_task_id": task_ids[1]}},
    )
    assert current_scope != scopes[1]
    assert store.loads[load_count:] == [
        (initial.run_id, current_scope, 0),
        (initial.run_id, scopes[1], 1),
    ]
    assert store.rows[(initial.run_id, scopes[1])][0] == 2
    assert (initial.run_id, current_scope) not in store.rows
    assert calls == [0, 1] and gate_calls == [1]
    assert resumed_states[0].understanding_qa == before_crash[0].understanding_qa
    assert resumed_states[0].understanding_messages == before_crash[0].understanding_messages
    assert [message.id for message in result["messages"]] == ["old-user", "old-first", "old-second"]
    for key, value in second_update.items():
        if key != "messages":
            assert result[key] == value


@pytest.mark.parametrize("submitted", [{}, {"party": {"adults": 1}}])
async def test_submitted_identity_never_replays_old_scope(submitted):
    store = RecordingJournalStore()
    old = LegacyState(run_id="run", user_query="旅行", current_time="2026-11-09")
    task_id = "same-task"
    old_scope = legacy_understanding_scope(old, task_id)
    await store.save(old.run_id, old_scope, 0, {"worker_result": {"current_requirements": "旧结果"}})
    state = TravelAgentState.model_validate(old.model_dump(mode="json")).model_copy(
        update={"submitted_trip_identity": submitted},
    )
    config = {"configurable": {"worker_journal_store": store, "__pregel_task_id": task_id}}
    calls = []

    async def worker(state, config):
        calls.append(current_worker_journal.get().scope_id)
        return {"current_requirements": "新结果"}

    result = await with_worker_recovery(NODE_UNDERSTANDING_AGENT, worker)(state, config)
    new_scope = invocation_scope(state, NODE_UNDERSTANDING_AGENT, config)
    assert new_scope != old_scope
    assert result == {"current_requirements": "新结果"}
    assert calls == [new_scope]
    assert store.loads == [(old.run_id, new_scope, 0)]
    assert store.rows[(old.run_id, old_scope)][1]["worker_result"] == {"current_requirements": "旧结果"}


@pytest.mark.parametrize("current_has_result", [False, True])
async def test_existing_current_scope_takes_precedence_over_old_scope(current_has_result):
    store = RecordingJournalStore()
    old = LegacyState(run_id="run", user_query="旅行", current_time="2026-11-09")
    state = TravelAgentState.model_validate(old.model_dump(mode="json"))
    task_id = "same-task"
    config = {"configurable": {"worker_journal_store": store, "__pregel_task_id": task_id}}
    old_scope = legacy_understanding_scope(old, task_id)
    new_scope = invocation_scope(state, NODE_UNDERSTANDING_AGENT, config)
    assert state.submitted_trip_identity is None and old_scope != new_scope
    await store.save(old.run_id, old_scope, 0, {"worker_result": {"current_requirements": "旧结果"}})
    payload = {"worker_result": {"current_requirements": "当前结果"}} if current_has_result else {"progress": "进行中"}
    await store.save(old.run_id, new_scope, 0, payload)
    calls = []

    async def worker(state, config):
        journal = current_worker_journal.get()
        calls.append((journal.scope_id, journal.payload.get("progress")))
        return {"current_requirements": "新结果"}

    result = await with_worker_recovery(NODE_UNDERSTANDING_AGENT, worker)(state, config)
    assert result == {"current_requirements": "当前结果" if current_has_result else "新结果"}
    assert calls == ([] if current_has_result else [(new_scope, "进行中")])
    assert store.loads == [(old.run_id, new_scope, 1)]
    assert store.rows[(old.run_id, old_scope)] == (1, {"worker_result": {"current_requirements": "旧结果"}})


async def test_non_understanding_worker_does_not_attempt_legacy_lookup():
    store = RecordingJournalStore()
    state = TravelAgentState(run_id="run", agent_assignments={"worker": {"objective": "research"}})
    config = {"configurable": {"worker_journal_store": store, "__pregel_task_id": "task"}}
    calls = []

    async def worker(state, config):
        calls.append(current_worker_journal.get().scope_id)
        return {"current_requirements": "新结果"}

    result = await with_worker_recovery("worker", worker)(state, config)
    scope = invocation_scope(state, "worker", config)
    assert result == {"current_requirements": "新结果"}
    assert calls == [scope]
    assert store.loads == [(state.run_id, scope, 0)]
