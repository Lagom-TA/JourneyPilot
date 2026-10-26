"""图缓存、命令包装、入口检查与交付持久化在各工作流边界上的行为。"""

import asyncio
import inspect
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import MemorySaver

from travel_agent.conversation import graph as answer_graph
from travel_agent.conversation.workflow import FastAnswerWorkflow
from travel_agent.planning import graph as planning_graph
from travel_agent.planning.delivery import persistence
from travel_agent.planning.execution import with_run_control
from travel_agent.planning.requirements import amendments, entry
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.context import current_run_id, node_lifecycle_sink
from travel_agent.runtime.run_contracts import TripRunStatus
from travel_agent.storage.delivery_bundle_store import InMemoryDeliveryBundleStore
from travel_agent.storage.trip_run_store import InMemoryTripRunStore


def test_graph_caches_share_only_the_same_checkpointer(monkeypatch):
    monkeypatch.setattr(planning_graph, "_compiled_graph", None)
    monkeypatch.setattr(planning_graph, "_compiled_graphs_with_checkpointer", {})
    monkeypatch.setattr(answer_graph, "_compiled_fast_graph", None)
    first, second = MemorySaver(), MemorySaver()

    plain = planning_graph.get_travel_graph()
    persisted = planning_graph.get_travel_graph(first)
    assert planning_graph.get_travel_graph() is plain
    assert planning_graph.get_travel_graph(first) is persisted
    assert planning_graph.get_travel_graph(second) is not persisted
    assert persisted is not plain
    assert persisted.checkpointer is first
    assert not plain.interrupt_before_nodes
    assert not persisted.interrupt_before_nodes
    assert answer_graph.get_fast_graph() is answer_graph.get_fast_graph()


async def test_amendment_adapter_preserves_async_run_control_and_sync_policy(
    monkeypatch,
):
    observed = []
    expected = {"intent_amendment_route": "itinerary_planner"}

    def policy(state):
        observed.append((state, asyncio.get_running_loop()))
        return expected

    monkeypatch.setattr(amendments, "apply_runtime_amendments", policy)
    state = TravelAgentState()
    assert not inspect.iscoroutinefunction(amendments.apply_runtime_amendments)
    assert inspect.iscoroutinefunction(amendments.intent_amendment_router_node)
    wrapped = with_run_control(
        "intent_amendment_router", amendments.intent_amendment_router_node
    )
    assert await wrapped(state) is expected
    assert observed == [(state, asyncio.get_running_loop())]


@pytest.mark.parametrize("compaction_fails", [False, True])
async def test_entry_checks_identity_after_best_effort_compaction(
    monkeypatch, compaction_fails
):
    calls = []
    queue = asyncio.Queue()

    async def compact(state, stream_queue, system_prompt):
        calls.append((state.run_id, stream_queue, system_prompt))
        if compaction_fails:
            raise RuntimeError("session measurement unavailable")
        return {"session_compressed": True}

    monkeypatch.setattr(entry, "_check_and_handle_compaction_deep", compact)
    state = TravelAgentState(run_id="run_missing_identity")
    with pytest.raises(entry.ScopeIdentityError) as caught:
        await entry.clarifier_node(state, {"configurable": {"stream_queue": queue}})
    assert caught.value.run_id == state.run_id
    assert calls == [(state.run_id, queue, entry.SCOPE_CONTEXT_SYSTEM_PROMPT)]


async def test_fast_workflow_preserves_update_snapshot_and_lifecycle_order(monkeypatch):
    queue = asyncio.Queue()
    snapshot = {"run_id": "run_fast_boundary", "is_completed": True}
    update = {"fast_answer_agent": {"is_completed": True}}
    lifecycle = {"node": "fast_answer_agent", "status": "completed"}

    class Graph:
        async def astream(self, state, *, stream_mode, config):
            assert stream_mode == ["updates", "values"]
            assert config["configurable"]["thread_id"] == state.run_id
            assert config["configurable"]["stream_queue"] is queue
            assert current_run_id.get() == state.run_id
            await node_lifecycle_sink.get()(lifecycle)
            yield "updates", update
            yield "values", snapshot

    monkeypatch.setattr(
        "travel_agent.conversation.workflow.get_fast_graph", lambda: Graph()
    )
    before = SimpleNamespace(run=current_run_id.get(), sink=node_lifecycle_sink.get())
    frames = [
        frame
        async for frame in FastAnswerWorkflow().astream(
            "苏州适合玩几天？",
            "session_fast_boundary",
            run_id="run_fast_boundary",
            stream_queue=queue,
        )
    ]
    assert frames == [update, {"__final_state__": snapshot}]
    assert queue.get_nowait() == ("node_lifecycle", lifecycle)
    assert queue.get_nowait() == ("state_snapshot", snapshot)
    assert queue.empty()
    assert current_run_id.get() == before.run
    assert node_lifecycle_sink.get() is before.sink


@pytest.mark.parametrize("failure", [None, "readback", "completion"])
async def test_initial_delivery_keeps_commit_readback_and_terminal_in_one_transaction(
    monkeypatch, failure
):
    calls = []
    session = object()
    state = TravelAgentState(run_id="run_atomic_boundary")
    manifest = SimpleNamespace(
        run_id=state.run_id,
        bundle_id="bundle_atomic_boundary",
        model_dump=lambda **_: {"bundle_id": "bundle_atomic_boundary"},
    )
    bundle = SimpleNamespace(manifest=manifest)

    @asynccontextmanager
    async def transaction():
        calls.append("begin")
        try:
            yield session
        except RuntimeError:
            calls.append("rollback")
            raise
        else:
            calls.append("commit")

    class Bundles:
        async def commit(self, **kwargs):
            assert kwargs["session"] is session
            assert kwargs["bundle"] is bundle
            assert kwargs["idempotency_key"] == f"{state.run_id}:delivery:create"
            calls.append("bundle")
            return SimpleNamespace(bundle=bundle)

        async def get_current_in_session(self, actual_session, run_id):
            assert actual_session is session and run_id == state.run_id
            calls.append("readback")
            if failure == "readback":
                return None
            return bundle

    class Runs:
        async def complete_delivery(self, run_id, **kwargs):
            assert kwargs["session"] is session and run_id == state.run_id
            assert kwargs["bundle_id"] == manifest.bundle_id
            calls.append("terminal")
            if failure == "completion":
                raise RuntimeError("terminal event rejected")
            return SimpleNamespace(status=TripRunStatus.COMPLETED), object(), object()

    monkeypatch.setattr(persistence, "get_db_session", transaction)
    operation = persistence._commit_initial_delivery_atomically(
        bundle_store=Bundles(), trip_store=Runs(), state=state, bundle=bundle
    )
    if failure:
        with pytest.raises(RuntimeError):
            await operation
        expected = ["begin", "bundle", "readback"]
        if failure == "completion":
            expected.append("terminal")
        assert calls == [*expected, "rollback"]
    else:
        assert await operation is bundle
        assert calls == ["begin", "bundle", "readback", "terminal", "commit"]


@pytest.mark.parametrize("failure", ["readback", "completion"])
async def test_initial_delivery_restores_both_in_memory_stores_on_failure(failure):
    state = TravelAgentState(run_id="run_memory_boundary")
    manifest = SimpleNamespace(
        run_id=state.run_id,
        bundle_id="bundle_memory_boundary",
        model_dump=lambda **_: {"bundle_id": "bundle_memory_boundary"},
    )
    bundle = SimpleNamespace(manifest=manifest)

    class Bundles(InMemoryDeliveryBundleStore):
        async def commit(self, **kwargs):
            self._heads[state.run_id] = manifest.bundle_id
            return SimpleNamespace(bundle=bundle)

        async def get_current(self, run_id):
            return None if failure == "readback" else bundle

    class Runs(InMemoryTripRunStore):
        async def complete_delivery(self, run_id, **kwargs):
            self.events[run_id] = ["delivery.ready"]
            raise RuntimeError("terminal event rejected")

    bundles, runs = Bundles(), Runs()
    before_bundles = bundles.snapshot_for_initial_delivery()
    before_runs = runs.snapshot_for_initial_delivery()
    with pytest.raises(RuntimeError):
        await persistence._commit_initial_delivery_atomically(
            bundle_store=bundles, trip_store=runs, state=state, bundle=bundle
        )
    assert bundles.snapshot_for_initial_delivery() == before_bundles
    assert runs.snapshot_for_initial_delivery() == before_runs
