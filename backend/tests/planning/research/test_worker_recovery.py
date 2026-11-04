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
    JournalConflict, 
)
from tests.support.memory_stores import InMemoryWorkerJournalStore
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

    async def ainvoke_with_tools_events(self, messages, tools):
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
    assert len(llm.requests) == 2  # 完整的助手工具调用不会重新生成
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
    changed = state.model_copy(update={"current_requirements": "更新后的需求"})
    await recovered(changed, config)
    assert len(calls) == 2


async def test_understanding_without_assignment_replays_and_changes_scope():
    from travel_agent.planning.nodes import NODE_UNDERSTANDING_AGENT
    from travel_agent.planning.recovery import invocation_scope

    store = InMemoryWorkerJournalStore()
    state = TravelAgentState(run_id="run", user_query="旅行", current_time="2026-11-02")
    calls = []

    async def worker(state, config):
        calls.append(1)
        return {"understanding_rounds": 1}

    recovered = with_worker_recovery(NODE_UNDERSTANDING_AGENT, worker)
    config = {"configurable": {"worker_journal_store": store, "__pregel_task_id": "task-1"}}
    assert await recovered(state, config) == {"understanding_rounds": 1}
    assert await recovered(state, config) == {"understanding_rounds": 1}
    assert calls == [1]

    scope = invocation_scope(state, NODE_UNDERSTANDING_AGENT, config)
    changed_time = state.model_copy(update={"current_time": "2026-11-03"})
    changed_answer = state.model_copy(update={"understanding_rounds": 1})
    changed_task = {"configurable": {"__pregel_task_id": "task-2"}}
    assert invocation_scope(changed_time, NODE_UNDERSTANDING_AGENT, config) != scope
    assert invocation_scope(changed_answer, NODE_UNDERSTANDING_AGENT, config) != scope
    assert invocation_scope(state, NODE_UNDERSTANDING_AGENT, changed_task) != scope


@pytest.mark.parametrize("assignments", [{}, {"worker": {"objective": "  "}}])
async def test_other_workers_still_require_valid_assignment(assignments):
    state = TravelAgentState(run_id="run", agent_assignments=assignments)

    async def worker(state, config):
        pytest.fail("缺少任务分配时不能执行")

    recovered = with_worker_recovery("worker", worker)
    config = {"configurable": {"worker_journal_store": InMemoryWorkerJournalStore()}}
    with pytest.raises(ValueError, match="missing capability assignment for worker"):
        await recovered(state, config)


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


async def test_cancellation_is_not_converted_to_a_failed_fallback(monkeypatch):
    from travel_agent.runtime.cancellation import RunCancelled
    from travel_agent.runtime.context import current_run_id
    from travel_agent.runtime.budget import reset_ledgers
    from travel_agent.tools import fallback
    from travel_agent.tools.gateway_contracts import ToolManifest
    from travel_agent.tools.registry import ToolRegistry

    registry = ToolRegistry()
    async def failing():
        return {"success": False, "error": "offline fixture failure"}
    async def cancelled():
        raise RunCancelled("run", "worker")
    registry.register("main_fixture", "主工具", {"type": "object"}, failing,
                      manifest=ToolManifest(tool_name="main_fixture", allow_offline_fallback=True))
    registry.register("fallback_fixture", "备用工具", {"type": "object"}, cancelled,
                      manifest=ToolManifest(tool_name="fallback_fixture"))
    monkeypatch.setattr(execution, "get_tool_registry", lambda: registry)
    monkeypatch.setattr(fallback, "get_fallback_tool", lambda _name: ("fallback_fixture", "fixture"))
    monkeypatch.setattr(fallback, "build_fallback_args", lambda *_args: {})
    token = current_run_id.set("run")
    reset_ledgers()
    try:
        with pytest.raises(RunCancelled):
            await execution.execute_tool("main_fixture", {}, max_retries=0)
    finally:
        current_run_id.reset(token)


async def test_cancelled_run_does_not_replay_a_cached_tool_result(monkeypatch):
    from types import SimpleNamespace
    from travel_agent.runtime.cancellation import RunCancelled, run_control_registry
    from travel_agent.runtime.context import current_run_id

    journal = WorkerJournal(InMemoryWorkerJournalStore(), "run", "scope", 0, {}, None)
    key = journal.next_tool("read", {})
    journal.tool_cursor = 0
    journal.payload["tools"] = {key: {"result": {"status": "success"}}}
    monkeypatch.setattr(execution, "get_tool_registry", lambda: SimpleNamespace(get_tool_metadata=lambda _name: {}))
    handle = run_control_registry.register("run")
    handle.request_stop("user_cancel")
    run_token = current_run_id.set("run")
    journal_token = current_worker_journal.set(journal)
    try:
        with pytest.raises(RunCancelled):
            await execution.execute_tool("read", {})
    finally:
        current_worker_journal.reset(journal_token)
        current_run_id.reset(run_token)
        run_control_registry.clear()


async def test_cancellation_stops_station_lookup_before_provider_fallback(monkeypatch):
    from travel_agent.planning.itinerary import place_resolution
    from travel_agent.planning.research.transport.rail import stations
    from travel_agent.runtime.cancellation import RunCancelled

    calls = []
    async def cancelled(**_kwargs):
        calls.append("amap")
        raise RunCancelled("run", "transport_researcher")
    async def forbidden(**_kwargs):
        calls.append("nominatim")
        pytest.fail("取消后不能发起另一个地点查询")

    monkeypatch.setattr(place_resolution, "_resolve_via_amap", cancelled)
    monkeypatch.setattr(place_resolution, "_resolve_via_nominatim", forbidden)
    with pytest.raises(RunCancelled):
        await stations._locate_rail_station(
            telecode="SHH", station_name="上海", city="上海",
            city_identity={"place_id": "shanghai", "country_code": "CN", "latitude": 31.2, "longitude": 121.4},
            tool_context={}, point_cache={},
        )
    assert calls == ["amap"]


@pytest.mark.parametrize("cancel_at", ["station_codes", "tickets"])
async def test_cancellation_stops_rail_ticket_prefetch(monkeypatch, cancel_at):
    from datetime import date
    from types import SimpleNamespace
    from travel_agent.planning.research.provider_contracts import ProviderRouteLegScope
    from travel_agent.planning.research.transport.rail import binding
    from travel_agent.runtime.cancellation import RunCancelled

    async def cancelled(*_args, **_kwargs):
        raise RunCancelled("run", "transport_researcher")

    monkeypatch.setattr(binding, "get_tool_registry", lambda: SimpleNamespace(has_tool=lambda _name: True))
    monkeypatch.setattr(binding, "execute_tool", cancelled)
    if cancel_at == "tickets":
        monkeypatch.setattr(binding, "_builtin_station_telecode", lambda city: {"上海": "SHH", "杭州": "HZH"}.get(city))
        monkeypatch.setattr(binding, "get_tool_registry", lambda: SimpleNamespace(has_tool=lambda name: name == "get-tickets"))
    origin = {"place_id": "shanghai", "name": "上海", "country_code": "CN"}
    destination = {"place_id": "hangzhou", "name": "杭州", "country_code": "CN"}
    leg = ProviderRouteLegScope(leg_role="outbound", from_place_id="shanghai", to_place_id="hangzhou", service_date=date(2026, 11, 5))
    with pytest.raises(RunCancelled):
        await binding._bind_one_rail_leg(
            state=TravelAgentState(run_id="run"), messages=[], tool_context={}, authoritative_tool_results=[],
            reference_services=[], scoped_leg=leg, identity_by_place_id={"shanghai": origin, "hangzhou": destination},
            station_code_cache={}, station_point_cache={}, now=None,
        )


async def test_stream_without_finish_never_admits_partial_json(tools):
    class Partial:
        async def ainvoke_with_tools_events(self, *a):
            yield {"type": "text_delta", "content": '{"candidate":'}
    result = await react.streaming_react_loop(Partial(), [], tools, None, "worker")
    assert result.content == ""


async def test_old_workflow_cache_cannot_bypass_gateway(monkeypatch, tools):
    class LLM:
        async def ainvoke_with_tools_events(self, messages, schemas):
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
            raise RuntimeError("crash before delivery finalization")
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
    # 像新的执行器那样重建图。saver 保留带类型的 checkpoint 与 pending writes，
    # journal 保留进入 Pregel 之前的结果。
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
    from tests.support.memory_stores import InMemoryToolAuditStore
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
        async def ainvoke_with_tools_events(self, messages, schemas):
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
        async def ainvoke_with_tools_events(self, messages, schemas):
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
        async def ainvoke_with_tools_events(self, messages, schemas):
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
