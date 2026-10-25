import asyncio
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from travel_agent.planning.recovery import with_worker_recovery
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.journal import WorkerJournal, current_worker_journal
from travel_agent.storage.worker_journal_store import (
    InMemoryWorkerJournalStore,
    JournalConflict,
)
from travel_agent.tools import execution, react
from travel_agent.tools.exposure import ToolExposurePlan


@pytest.fixture
def tools(monkeypatch):
    schema = {"type": "function", "function": {"name": "read", "parameters": {"type": "object"}}}
    items = [{"schema": schema}]
    monkeypatch.setattr(react, "apply_tool_exposure", lambda *a: ToolExposurePlan(False, "worker", (schema,), "", 0, 0, 1, 1))
    return items


class FakeLLM:
    def __init__(self):
        self.requests = []

    async def astream_with_tools(self, messages, tools):
        self.requests.append(deepcopy(messages))
        if len(self.requests) == 1:
            yield {"type": "finish", "content": "", "tool_calls": [
                {"id": "tc1", "name": "read", "arguments": {"n": 1}},
                {"id": "tc2", "name": "read", "arguments": {"n": 2}},
            ], "assistant_replay": {"reasoning_content": "opaque"}}
        else:
            yield {"type": "finish", "content": "packet", "tool_calls": []}


async def test_resume_between_tools_keeps_pairing_and_completed_results(monkeypatch, tools):
    store = InMemoryWorkerJournalStore()
    journal = WorkerJournal(store, "run", "scope", 0, {}, None)
    llm = FakeLLM()
    executed = []

    async def execute(name, args, *a, **kw):
        executed.append(args["n"])
        return {"status": "success", "sanitized_result": {"n": args["n"]}, "audit_id": f"a{args['n']}"}

    monkeypatch.setattr(react, "execute_tool", execute)
    def stop(node):
        if executed == [1]:
            raise asyncio.CancelledError()
    monkeypatch.setattr(react, "check_cancel_requested", stop)
    token = current_worker_journal.set(journal)
    try:
        with pytest.raises(asyncio.CancelledError):
            await react.streaming_react_loop(llm, [{"role": "system", "content": "fixed"}], tools, None, "worker")
    finally:
        current_worker_journal.reset(token)
    version, payload = await store.load("run", "scope")
    assert payload["react"]["next_tool"] == 1
    assert payload["react"]["messages"][-1]["tool_call_id"] == "tc1"
    monkeypatch.setattr(react, "check_cancel_requested", lambda *a: None)
    token = current_worker_journal.set(WorkerJournal(store, "run", "scope", version, payload, None))
    transcript = []
    try:
        result = await react.streaming_react_loop(llm, transcript, tools, None, "worker")
    finally:
        current_worker_journal.reset(token)
    assert executed == [1, 2]
    assert len(llm.requests) == 2  # complete assistant tool call is never regenerated
    assert result.content == "packet" and len(result.tool_results) == 2
    assert [m["tool_call_id"] for m in transcript if m["role"] == "tool"] == ["tc1", "tc2"]
    assert transcript[1]["assistant_replay"]["reasoning_content"] == "opaque"


async def test_worker_result_replay_before_graph_checkpoint():
    store = InMemoryWorkerJournalStore()
    state = TravelAgentState(run_id="run", agent_assignments={"worker": {"objective": "research"}})
    calls = []
    async def worker(state, config):
        calls.append(1)
        return {"messages": [AIMessage(content="typed result", id="stable")], "agent_status": {"worker": "completed"}}
    recovered = with_worker_recovery("worker", worker)
    config = {"configurable": {"worker_journal_store": store}}
    first = await recovered(state, config)
    second = await recovered(state, config)
    assert first == second and calls == [1]
    assert second["messages"][0].id == "stable"
    changed = state.model_copy(update={"intent_spec_revision": 2})
    await recovered(changed, config)
    assert len(calls) == 2


async def test_stale_writer_cannot_commit():
    store = InMemoryWorkerJournalStore()
    await store.save("run", "scope", 0, {"a": 1})
    with pytest.raises(JournalConflict):
        await store.save("run", "scope", 0, {"a": 2})


async def test_tool_outcome_commit_replays_before_transcript_commit(monkeypatch):
    from types import SimpleNamespace
    store = InMemoryWorkerJournalStore()
    journal = WorkerJournal(store, "run", "scope", 0, {}, None)
    calls = []
    monkeypatch.setattr(execution, "get_tool_registry", lambda: SimpleNamespace(get_tool_metadata=lambda name: {}))
    async def execute(*a, **kw):
        calls.append(1)
        return {"status": "success", "audit_id": "fixed", "sanitized_result": {"value": 1}}
    monkeypatch.setattr(execution, "_execute_tool_once", execute)
    token = current_worker_journal.set(journal)
    try:
        first = await execution.execute_tool("read", {})
    finally:
        current_worker_journal.reset(token)
    version, payload = await store.load("run", "scope")
    token = current_worker_journal.set(WorkerJournal(store, "run", "scope", version, payload, None))
    try:
        second = await execution.execute_tool("read", {})
    finally:
        current_worker_journal.reset(token)
    assert first == second and calls == [1]


async def test_unknown_side_effect_is_not_reexecuted(monkeypatch):
    from types import SimpleNamespace

    from travel_agent.tools.gateway_contracts import ToolManifest
    store = InMemoryWorkerJournalStore()
    journal = WorkerJournal(store, "run", "scope", 0, {}, None)
    key = journal.next_tool("write", {})
    journal.tool_cursor = 0
    journal.payload["tools"] = {key: {"phase": "started"}}
    manifest = ToolManifest(tool_name="write", side_effecting=True)
    monkeypatch.setattr(execution, "get_tool_registry", lambda: SimpleNamespace(get_tool_metadata=lambda name: {"manifest": manifest}))
    async def forbidden(*a, **kw):
        pytest.fail("uncertain write was repeated")
    monkeypatch.setattr(execution, "_execute_tool_once", forbidden)
    token = current_worker_journal.set(journal)
    try:
        result = await execution.execute_tool("write", {})
    finally:
        current_worker_journal.reset(token)
    assert result["status"] == "failed"
    assert "unknown" in str(result["error"])


async def test_ask_user_pairs_all_tool_calls_before_exit(monkeypatch, tools):
    llm = FakeLLM()
    async def asking(*a, **kw):
        return {"type": "user_input_required", "question": "destination?", "status": "success"}
    monkeypatch.setattr(react, "execute_tool", asking)
    messages = [{"role": "system", "content": "fixed"}]
    result = await react.streaming_react_loop(llm, messages, tools, None, "worker", can_ask_user=True)
    assert result.pending_choice["question"] == "destination?"
    assert [m["tool_call_id"] for m in messages if m["role"] == "tool"] == ["tc1", "tc2"]
    assert "awaiting_user_input" in messages[-1]["content"]


async def test_stream_without_finish_never_admits_partial_json(tools):
    class Partial:
        async def astream_with_tools(self, *a):
            yield {"type": "text_delta", "content": '{"candidate":'}
    result = await react.streaming_react_loop(Partial(), [], tools, None, "worker")
    assert result.content == ""


async def test_old_workflow_cache_cannot_bypass_gateway(monkeypatch, tools):
    class LLM:
        async def astream_with_tools(self, messages, schemas):
            if any(m["role"] == "tool" for m in messages):
                yield {"type": "finish", "content": "finished", "tool_calls": []}
            else:
                yield {"type": "finish", "content": "", "tool_calls": [{"id": "a", "name": "read", "arguments": {}}]}
    executed = []
    async def execute(*a, **kw):
        executed.append(1)
        return {"status": "success", "audit_id": "current", "sanitized_result": {}}
    monkeypatch.setattr(react, "execute_tool", execute)
    old_cache = {react._make_cache_key("read", {}): {"status": "success", "audit_id": "old"}}
    result = await react.streaming_react_loop(LLM(), [], tools, None, "worker", tool_cache=old_cache)
    assert executed == [1] and result.tool_results[0]["audit_id"] == "current"


@pytest.mark.parametrize("crash_boundary", ["before_pending_write", "after_pending_write"])
async def test_langgraph_fan_in_resume_preserves_typed_worker_updates(crash_boundary):
    from tests.fixtures.research_packets import make_packet

    sibling_committed = asyncio.Event()
    class Saver(InMemorySaver):
        async def aput_writes(self, config, writes, task_id, task_path=""):
            await super().aput_writes(config, writes, task_id, task_path)
            if any(channel == "agent_status" and value.get("lodging") == "completed"
                   for channel, value in writes):
                sibling_committed.set()

    saver, store = Saver(), InMemoryWorkerJournalStore()
    calls, gate_calls, crash = [], [], [True]
    def worker_for(name):
        async def worker(state: TravelAgentState, config: RunnableConfig):
            calls.append(name)
            packet = make_packet(packet_id=name, entities=((name, "tokyo"),))
            return {"research_packets": {name: packet},
                    "messages": [AIMessage(content=name)],
                    "agent_status": {name: "completed"}}
        return with_worker_recovery(name, worker)

    recovered = worker_for("visit")
    async def visit(state: TravelAgentState, config: RunnableConfig):
        result = await recovered(state, config)
        if crash[0] and crash_boundary == "before_pending_write":
            await asyncio.wait_for(sibling_committed.wait(), timeout=5)
            crash[0] = False
            raise RuntimeError("crash after journal before Pregel write")
        return result

    async def gate(state: TravelAgentState):
        if crash[0] and crash_boundary == "after_pending_write":
            crash[0] = False
            raise RuntimeError("crash before gate admission")
        gate_calls.append(state)
        assert set(state.research_packets) == {"visit", "lodging"}
        assert all(packet.source_records for packet in state.research_packets.values())
        return {}

    def compile_graph():
        builder = StateGraph(TravelAgentState)
        builder.add_node("visit", visit)
        builder.add_node("lodging", worker_for("lodging"))
        builder.add_node("gate", gate)
        builder.add_edge(START, "visit")
        builder.add_edge(START, "lodging")
        builder.add_edge(["visit", "lodging"], "gate")
        builder.add_edge("gate", END)
        return builder.compile(checkpointer=saver)

    config = {"configurable": {"thread_id": "run_test", "worker_journal_store": store}}
    graph = compile_graph()
    with pytest.raises(RuntimeError, match="crash"):
        await graph.ainvoke(TravelAgentState(run_id="run_test", agent_assignments={
            name: {"objective": f"research {name}"} for name in ("visit", "lodging")
        }), config)
    # Reconstruct the graph as a new executor would. The saver keeps typed
    # checkpoint/pending writes; the journal keeps the pre-Pregel result.
    result = await compile_graph().ainvoke(None, config)
    assert sorted(calls) == ["lodging", "visit"]
    assert len(gate_calls) == 1
    assert len(result["messages"]) == 2
    assert len({message.id for message in result["messages"]}) == 2
    assert set(result["research_packets"]) == {"visit", "lodging"}


async def test_new_langgraph_dispatch_does_not_replay_previous_failed_attempt():
    store, calls = InMemoryWorkerJournalStore(), []
    async def worker(state: TravelAgentState, config: RunnableConfig):
        calls.append(state.current_plan_step)
        return {"agent_status": {"worker": "failed" if len(calls) == 1 else "completed"}}

    async def dispatch(state: TravelAgentState):
        return {"current_plan_step": state.current_plan_step + 1}

    builder = StateGraph(TravelAgentState)
    builder.add_node("worker", with_worker_recovery("worker", worker))
    builder.add_node("dispatch", dispatch)
    builder.add_edge(START, "worker")
    builder.add_edge("worker", "dispatch")
    builder.add_conditional_edges("dispatch", lambda state: "worker" if state.current_plan_step < 2 else END)
    graph = builder.compile(checkpointer=InMemorySaver())
    result = await graph.ainvoke(TravelAgentState(run_id="run_test",
        agent_assignments={"worker": {"objective": "research"}}),
        {"configurable": {"thread_id": "run_test", "worker_journal_store": store}})
    assert calls == [0, 1]
    assert result["agent_status"]["worker"] == "completed"


async def test_repeated_side_effecting_tool_calls_are_never_locally_cached(monkeypatch):
    from travel_agent.storage.tool_audit_store import InMemoryToolAuditStore
    from travel_agent.tools.gateway_contracts import ToolManifest
    from travel_agent.tools.registry import ToolRegistry

    registry, calls, audit = ToolRegistry(), [], InMemoryToolAuditStore()
    async def write():
        calls.append(1)
        return {"success": True}
    registry.register("fixture_write", "fixture write", {"type": "object"}, write,
                      manifest=ToolManifest(tool_name="fixture_write", side_effecting=True))
    monkeypatch.setattr(execution, "get_tool_registry", lambda: registry)
    class LLM:
        async def astream_with_tools(self, messages, schemas):
            tool_calls = [] if any(m["role"] == "tool" for m in messages) else [
                {"id": str(n), "name": "fixture_write", "arguments": {}} for n in (1, 2)]
            yield {"type": "finish", "content": "", "tool_calls": tool_calls}
    result = await react.streaming_react_loop(LLM(), [], registry.get_tools_as_schemas(), None,
        "worker", tool_context={"run_id": "run_test", "tool_audit_store": audit})
    assert calls == [1, 1]
    assert len({envelope["audit_id"] for envelope in result.tool_results}) == 2


@pytest.mark.parametrize("scenario, expected", [
    ("final", "final_answer"),
    ("exception", "model_failed"),
    ("partial", "incomplete_stream"),
    ("empty", "incomplete_stream"),
    ("empty_after_delta", "incomplete_stream"),
    ("tool_failure", "model_failed"),
    ("limit", "iteration_limit"),
    ("budget", "budget_limit"),
])
async def test_terminal_outcomes_and_journal_replay_are_identical(monkeypatch, tools, scenario, expected):
    from travel_agent.runtime.operations import ModelWindowClosed
    from travel_agent.tools.result import ReactOutcome

    calls = []
    executed = []

    class Model:
        async def astream_with_tools(self, messages, schemas):
            calls.append(1)
            if scenario == "exception" or scenario == "tool_failure" and len(calls) > 1:
                raise RuntimeError("fixture-model-error")
            if scenario == "partial":
                yield {"type": "text_delta", "content": "我再查一下"}
                return
            if scenario in {"tool_failure", "limit"}:
                yield {"type": "finish", "content": "我再查一下", "tool_calls": [
                    {"id": "read_1", "name": "read", "arguments": {}}]}
                return
            if scenario == "empty_after_delta":
                yield {"type": "text_delta", "content": "我再查一下"}
            yield {"type": "finish", "content": "有效的最终回答" if scenario == "final" else "", "tool_calls": []}

    async def execute(*args, **kwargs):
        executed.append(1)
        return {"status": "success", "sanitized_result": {"name": "City Park"}, "audit_id": "fixture_audit"}

    def remaining(*args):
        if scenario == "budget":
            from types import SimpleNamespace
            raise ModelWindowClosed("fixture-budget-ended", SimpleNamespace(elapsed_seconds=360), "research")

    monkeypatch.setattr(react, "execute_tool", execute)
    monkeypatch.setattr(react, "remaining_model_seconds", remaining)
    store = InMemoryWorkerJournalStore()
    journal = WorkerJournal(store, "run", "scope", 0, {}, None)
    token = current_worker_journal.set(journal)
    try:
        first = await react.streaming_react_loop(Model(), [], tools, None, "worker", max_iterations=1 if scenario == "limit" else 2)
    finally:
        current_worker_journal.reset(token)
    assert first.outcome.value == expected
    assert first.content == ("有效的最终回答" if scenario == "final" else "")
    if scenario in {"exception", "tool_failure"}:
        assert "fixture-model-error" in first.error and "worker iteration" in first.error
    if scenario in {"tool_failure", "limit"}:
        assert first.tool_results[0]["audit_id"] == "fixture_audit"
        assert first.summaries and executed == [1]
    if first.outcome is ReactOutcome.FINAL_ANSWER:
        assert first.require_final_answer() == first.content
    else:
        with pytest.raises(RuntimeError, match=expected):
            first.require_final_answer()
    version, payload = await store.load("run", "scope")
    assert payload["react"]["done"] and payload["react"]["outcome"] == expected
    count = len(calls)
    token = current_worker_journal.set(WorkerJournal(store, "run", "scope", version, payload, None))
    try:
        replayed = await react.streaming_react_loop(Model(), [], tools, None, "worker")
    finally:
        current_worker_journal.reset(token)
    assert replayed == first and len(calls) == count
    if scenario != "final":
        with pytest.raises(RuntimeError, match=expected):
            replayed.require_final_answer()


@pytest.mark.parametrize("limit", [False, True])
async def test_worker_recovery_never_records_a_completed_fast_answer_after_loop_failure(monkeypatch, tools, limit):
    calls = []

    class Model:
        async def astream_with_tools(self, messages, schemas):
            calls.append(1)
            if not limit:
                raise RuntimeError("fixture-model-error")
            yield {"type": "finish", "content": "我再查一下", "tool_calls": [
                {"id": "read_1", "name": "read", "arguments": {}}]}

    async def execute(*args, **kwargs):
        return {"status": "success", "sanitized_result": {"name": "City Park"}, "audit_id": "fixture_audit"}

    monkeypatch.setattr(react, "execute_tool", execute)
    store = InMemoryWorkerJournalStore()
    current = TravelAgentState(run_id="run_test", agent_assignments={"worker": {"objective": "answer"}})
    config = {"configurable": {"worker_journal_store": store}}

    async def worker(state, config):
        result = await react.streaming_react_loop(Model(), [], tools, None, "worker", max_iterations=1)
        return {"messages": [AIMessage(content=result.require_final_answer())], "is_completed": True}

    recovered = with_worker_recovery("worker", worker)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="iteration_limit" if limit else "model_failed"):
            await recovered(current, config)
    from travel_agent.planning.recovery import invocation_scope
    _, payload = await store.load(current.run_id, invocation_scope(current, "worker", config))
    assert "worker_result" not in payload
    assert payload["react"]["outcome"] == ("iteration_limit" if limit else "model_failed")
    assert len(calls) == 1
