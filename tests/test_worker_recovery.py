import asyncio
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from travel_agent.agents import utils
from travel_agent.entities.state import TravelAgentState
from travel_agent.infrastructure.worker_journal_store import InMemoryWorkerJournalStore, JournalConflict
from travel_agent.tools.exposure import ToolExposurePlan
from travel_agent.workflows.worker_recovery import WorkerJournal, current_worker_journal, with_worker_recovery


@pytest.fixture
def tools(monkeypatch):
    schema = {"type": "function", "function": {"name": "read", "parameters": {"type": "object"}}}
    items = [{"schema": schema}]
    monkeypatch.setattr(utils, "apply_tool_exposure", lambda *a: ToolExposurePlan(False, "worker", (schema,), "", 0, 0, 1, 1))
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

    monkeypatch.setattr(utils, "execute_tool", execute)
    def stop(node):
        if executed == [1]:
            raise asyncio.CancelledError()
    monkeypatch.setattr(utils, "check_cancel_requested", stop)
    token = current_worker_journal.set(journal)
    try:
        with pytest.raises(asyncio.CancelledError):
            await utils.streaming_react_loop(llm, [{"role": "system", "content": "fixed"}], tools, None, "worker")
    finally:
        current_worker_journal.reset(token)
    version, payload = await store.load("run", "scope")
    assert payload["react"]["next_tool"] == 1
    assert payload["react"]["messages"][-1]["tool_call_id"] == "tc1"
    monkeypatch.setattr(utils, "check_cancel_requested", lambda *a: None)
    token = current_worker_journal.set(WorkerJournal(store, "run", "scope", version, payload, None))
    transcript = []
    try:
        result = await utils.streaming_react_loop(llm, transcript, tools, None, "worker")
    finally:
        current_worker_journal.reset(token)
    assert executed == [1, 2]
    assert len(llm.requests) == 2  # complete assistant tool call is never regenerated
    assert result[0] == "packet" and len(result[3]) == 2
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
    monkeypatch.setattr(utils, "get_tool_registry", lambda: SimpleNamespace(get_tool_metadata=lambda name: {}))
    async def execute(*a, **kw):
        calls.append(1)
        return {"status": "success", "audit_id": "fixed", "sanitized_result": {"value": 1}}
    monkeypatch.setattr(utils, "_execute_tool_once", execute)
    token = current_worker_journal.set(journal)
    try:
        first = await utils.execute_tool("read", {})
    finally:
        current_worker_journal.reset(token)
    version, payload = await store.load("run", "scope")
    token = current_worker_journal.set(WorkerJournal(store, "run", "scope", version, payload, None))
    try:
        second = await utils.execute_tool("read", {})
    finally:
        current_worker_journal.reset(token)
    assert first == second and calls == [1]


async def test_unknown_side_effect_is_not_reexecuted(monkeypatch):
    from types import SimpleNamespace
    from travel_agent.entities.tool_gateway import ToolManifest
    store = InMemoryWorkerJournalStore()
    journal = WorkerJournal(store, "run", "scope", 0, {}, None)
    key = journal.next_tool("write", {})
    journal.tool_cursor = 0
    journal.payload["tools"] = {key: {"phase": "started"}}
    manifest = ToolManifest(tool_name="write", side_effecting=True)
    monkeypatch.setattr(utils, "get_tool_registry", lambda: SimpleNamespace(get_tool_metadata=lambda name: {"manifest": manifest}))
    async def forbidden(*a, **kw):
        pytest.fail("uncertain write was repeated")
    monkeypatch.setattr(utils, "_execute_tool_once", forbidden)
    token = current_worker_journal.set(journal)
    try:
        result = await utils.execute_tool("write", {})
    finally:
        current_worker_journal.reset(token)
    assert result["status"] == "failed"
    assert "unknown" in str(result["error"])


async def test_ask_user_pairs_all_tool_calls_before_exit(monkeypatch, tools):
    llm = FakeLLM()
    async def asking(*a, **kw):
        return {"type": "user_input_required", "question": "destination?", "status": "success"}
    monkeypatch.setattr(utils, "execute_tool", asking)
    messages = [{"role": "system", "content": "fixed"}]
    result = await utils.streaming_react_loop(llm, messages, tools, None, "worker", can_ask_user=True)
    assert result[2]["question"] == "destination?"
    assert [m["tool_call_id"] for m in messages if m["role"] == "tool"] == ["tc1", "tc2"]
    assert "awaiting_user_input" in messages[-1]["content"]


async def test_stream_without_finish_never_admits_partial_json(tools):
    class Partial:
        async def astream_with_tools(self, *a):
            yield {"type": "text_delta", "content": '{"candidate":'}
    result = await utils.streaming_react_loop(Partial(), [], tools, None, "worker")
    assert result[0] == ""


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
    monkeypatch.setattr(utils, "execute_tool", execute)
    old_cache = {utils._make_cache_key("read", {}): {"status": "success", "audit_id": "old"}}
    result = await utils.streaming_react_loop(LLM(), [], tools, None, "worker", tool_cache=old_cache)
    assert executed == [1] and result[3][0]["audit_id"] == "current"


@pytest.mark.parametrize("crash_boundary", ["before_pending_write", "after_pending_write"])
async def test_langgraph_fan_in_resume_preserves_typed_worker_updates(crash_boundary):
    from tests.test_research_context import make_packet

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
    from travel_agent.entities.tool_gateway import ToolManifest
    from travel_agent.infrastructure.tool_audit_store import InMemoryToolAuditStore
    from travel_agent.tools.registry import ToolRegistry

    registry, calls, audit = ToolRegistry(), [], InMemoryToolAuditStore()
    async def write():
        calls.append(1)
        return {"success": True}
    registry.register("fixture_write", "fixture write", {"type": "object"}, write,
                      manifest=ToolManifest(tool_name="fixture_write", side_effecting=True))
    monkeypatch.setattr(utils, "get_tool_registry", lambda: registry)
    class LLM:
        async def astream_with_tools(self, messages, schemas):
            tool_calls = [] if any(m["role"] == "tool" for m in messages) else [
                {"id": str(n), "name": "fixture_write", "arguments": {}} for n in (1, 2)]
            yield {"type": "finish", "content": "", "tool_calls": tool_calls}
    result = await utils.streaming_react_loop(LLM(), [], registry.get_tools_as_schemas(), None,
        "worker", tool_context={"run_id": "run_test", "tool_audit_store": audit})
    assert calls == [1, 1]
    assert len({envelope["audit_id"] for envelope in result[3]}) == 2
