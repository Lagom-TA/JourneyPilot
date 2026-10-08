import asyncio
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage

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
