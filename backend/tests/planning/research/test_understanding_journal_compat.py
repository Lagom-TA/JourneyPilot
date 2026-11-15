from copy import deepcopy
import asyncio
import hashlib
import json

import pytest
from langchain_core.messages import AIMessage

from tests.support.memory_stores import InMemoryTripRunStore, InMemoryWorkerJournalStore
from travel_agent.planning.nodes import NODE_UNDERSTANDING_AGENT
from travel_agent.planning.recovery import invocation_scope, with_worker_recovery
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.cancellation import RunCancelled, run_control_registry
from travel_agent.runtime.context import current_run_id
from travel_agent.runtime.journal import (
    WorkerJournal,
    current_execution_lease,
    current_worker_journal,
)
from travel_agent.storage.worker_journal_store import JournalConflict
from travel_agent.tools import react
from travel_agent.tools.exposure import ToolExposurePlan


NODE = NODE_UNDERSTANDING_AGENT
RUN_ID = "run-compat"
TASK_ID = "task-1"
LEASE = "lease-compat"
MISSING = object()


class RecordingJournalStore(InMemoryWorkerJournalStore):
    def __init__(self):
        super().__init__()
        self.loads = []
        self.saves = []

    async def load(self, run_id, scope_id):
        self.loads.append((run_id, scope_id))
        return await super().load(run_id, scope_id)

    async def save(self, run_id, scope_id, version, payload, *, lease_token=None):
        self.saves.append((run_id, scope_id, version, deepcopy(payload), lease_token))
        return await super().save(
            run_id, scope_id, version, payload, lease_token=lease_token
        )


def make_state(submitted=MISSING, **changes):
    values = {
        "run_id": RUN_ID,
        "user_query": "去青岛旅行",
        "current_time": "2031-04-10",
        **changes,
    }
    if submitted is not MISSING:
        values["submitted_trip_identity"] = submitted
    return TravelAgentState.model_validate(values)


def make_config(store, *, task_id=TASK_ID, run_store=None):
    configurable = {"worker_journal_store": store, "__pregel_task_id": task_id}
    if run_store is not None:
        configurable["trip_run_store"] = run_store
    return {"configurable": configurable}


def old_scope(state, config):
    return invocation_scope(state, NODE, config, include_submitted_identity=False)


def independent_scope(*, include_submitted_identity):
    # 显式列出参与旧任务身份的字段，避免用实现本身推导预期。
    fields = {
        "run_id": RUN_ID,
        "user_query": "去青岛旅行",
        "controlled_trip_identity": {},
        "current_requirements": "",
        "research_plan": None,
        "planning_generation": None,
        "constraint_pack": {},
        "fact_data_revision": 0,
        "session_anchor": None,
        "preset_context": "",
        "weather_context": None,
        "recommendation_catalog": None,
        "research_packets": {},
        "messages": [],
        "understanding_messages": [],
        "understanding_qa": [],
        "understanding_rounds": 0,
        "understanding_pending_questions": None,
        "current_time": "2031-04-10",
        "plan_gate_amendment": None,
        "pending_intent_amendments": [],
        "refinement_context": "",
        "plan_gate_decision": None,
        "graph_task_id": TASK_ID,
    }
    if include_submitted_identity:
        fields["submitted_trip_identity"] = None
    digest = hashlib.sha256(
        json.dumps(fields, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return f"{NODE}:{digest}"


async def make_run_store():
    store = InMemoryTripRunStore()
    await store.create_run(
        run_id=RUN_ID,
        session_id="session-compat",
        user_id="local",
        mode="deep",
        controlled_trip_identity={"origin": "原始出发地"},
    )
    return store


def test_scope_distinguishes_null_from_omitted_field_with_independent_hash():
    store = RecordingJournalStore()
    config = make_config(store)
    missing = make_state()
    explicit_none = make_state(None)

    assert "submitted_trip_identity" not in missing.model_fields_set
    assert "submitted_trip_identity" in explicit_none.model_fields_set
    assert missing.submitted_trip_identity is explicit_none.submitted_trip_identity is None
    expected_current = independent_scope(include_submitted_identity=True)
    expected_old = independent_scope(include_submitted_identity=False)
    assert expected_current != expected_old
    for state in (missing, explicit_none):
        assert invocation_scope(state, NODE, config) == expected_current
        assert old_scope(state, config) == expected_old


@pytest.mark.parametrize("submitted", [MISSING, None], ids=["missing", "explicit-none"])
async def test_legacy_complete_result_replays_in_place_and_updates_run(submitted, monkeypatch):
    store = RecordingJournalStore()
    run_store = await make_run_store()
    state = make_state(submitted)
    config = make_config(store, run_store=run_store)
    current = independent_scope(include_submitted_identity=True)
    previous = independent_scope(include_submitted_identity=False)
    result = {
        "controlled_trip_identity": {
            "destinations": [{"name": "青岛"}],
            "party": {"adults": 2},
        },
        "messages": [AIMessage(content="已理解需求", id="stable-message")],
        "current_requirements": "海边休闲",
        "understanding_rounds": 1,
    }
    payload = {"worker_result": deepcopy(result), "saved_stage": {"done": True}}
    store.rows[(RUN_ID, previous)] = (6, deepcopy(payload))
    updates = []
    update_run = run_store.update_controlled_trip_identity

    async def record_update(run_id, *, controlled_trip_identity):
        updates.append((run_id, deepcopy(controlled_trip_identity), store.rows[(RUN_ID, previous)][0]))
        await update_run(run_id, controlled_trip_identity=controlled_trip_identity)

    monkeypatch.setattr(run_store, "update_controlled_trip_identity", record_update)

    async def worker(state, config):
        pytest.fail("完整 journal 不应再次执行理解节点")

    lease_token = current_execution_lease.set(LEASE)
    try:
        replayed = await with_worker_recovery(NODE, worker)(state, config)
    finally:
        current_execution_lease.reset(lease_token)

    assert replayed == result
    assert isinstance(replayed["messages"][0], AIMessage)
    assert replayed["messages"][0].id == "stable-message"
    assert store.loads == [(RUN_ID, current), (RUN_ID, previous)]
    assert store.saves == [(RUN_ID, previous, 6, payload, LEASE)]
    assert store.rows == {(RUN_ID, previous): (7, payload)}
    assert updates == [(RUN_ID, result["controlled_trip_identity"], 7)]
    assert (await run_store.get_run(RUN_ID)).controlled_trip_identity == result["controlled_trip_identity"]
    replayed["messages"][0].content = "已修改的副本"
    assert store.rows[(RUN_ID, previous)][1] == payload


async def test_legacy_partial_react_continues_in_place_without_repeating_tool(monkeypatch):
    store = RecordingJournalStore()
    state = make_state()
    config = make_config(store)
    current = invocation_scope(state, NODE, config)
    previous = old_scope(state, config)
    schema = {"type": "function", "function": {"name": "read", "parameters": {"type": "object"}}}
    tools = [{"schema": schema}]
    monkeypatch.setattr(
        react,
        "apply_tool_exposure",
        lambda *args: ToolExposurePlan(False, NODE, (schema,), "", 0, 0, 1, 1),
    )
    executed = []

    async def execute(name, args, *args_extra, **kwargs):
        executed.append(args["n"])
        return {"status": "success", "sanitized_result": {"n": args["n"]}, "audit_id": f"audit-{args['n']}"}

    monkeypatch.setattr(react, "execute_tool", execute)

    class Model:
        def __init__(self):
            self.requests = []

        async def ainvoke_with_tools_events(self, messages, schemas):
            self.requests.append(deepcopy(messages))
            if len(self.requests) == 1:
                yield {"type": "finish", "content": "", "tool_calls": [
                    {"id": "tool-1", "name": "read", "arguments": {"n": 1}},
                    {"id": "tool-2", "name": "read", "arguments": {"n": 2}},
                ]}
            else:
                yield {"type": "finish", "content": "理解完成", "tool_calls": []}

    model = Model()

    def interrupt_after_first_tool(node):
        if executed == [1]:
            raise asyncio.CancelledError()

    monkeypatch.setattr(react, "check_cancel_requested", interrupt_after_first_tool)
    seed = WorkerJournal(store, RUN_ID, previous, 0, {"saved_stage": "保留"}, LEASE)
    seed_token = current_worker_journal.set(seed)
    try:
        with pytest.raises(asyncio.CancelledError):
            await react.streaming_react_loop(
                model, [{"role": "system", "content": "理解旅行需求"}], tools, None, NODE,
                journal_key="understanding_react_0",
            )
    finally:
        current_worker_journal.reset(seed_token)

    initial_version, partial = deepcopy(store.rows[(RUN_ID, previous)])
    assert initial_version > 0
    assert partial["understanding_react_0"]["next_tool"] == 1
    assert "worker_result" not in partial
    assert executed == [1]
    store.loads.clear()
    store.saves.clear()
    monkeypatch.setattr(react, "check_cancel_requested", lambda *args: None)
    resumed = []
    transcript = []

    async def worker(state, config):
        journal = current_worker_journal.get()
        resumed.append((journal.scope_id, journal.version, journal.lease_token, deepcopy(journal.payload)))
        outcome = await react.streaming_react_loop(
            model, transcript, tools, None, NODE, journal_key="understanding_react_0"
        )
        return {"current_requirements": outcome.require_final_answer()}

    recovered = with_worker_recovery(NODE, worker)
    lease_token = current_execution_lease.set(LEASE)
    try:
        result = await recovered(state, config)
        replayed = await recovered(state, config)
    finally:
        current_execution_lease.reset(lease_token)

    assert result == replayed == {"current_requirements": "理解完成"}
    assert resumed == [(previous, initial_version, LEASE, partial)]
    assert executed == [1, 2]
    assert len(model.requests) == 2
    assert [message["tool_call_id"] for message in transcript if message["role"] == "tool"] == ["tool-1", "tool-2"]
    assert store.loads == [(RUN_ID, current), (RUN_ID, previous)] * 2
    assert all(save[1] == previous and save[4] == LEASE for save in store.saves)
    assert store.saves[0][2] == initial_version
    assert (RUN_ID, current) not in store.rows
    version, finished = store.rows[(RUN_ID, previous)]
    assert version > initial_version
    assert finished["saved_stage"] == "保留"
    assert finished["understanding_react_0"]["done"] is True
    assert finished["worker_result"] == result


@pytest.mark.parametrize(
    "current_payload",
    [{}, {"understanding_react_0": {"phase": "request_started", "iteration": 1}}],
    ids=["empty-payload", "partial-payload"],
)
async def test_existing_current_version_wins_over_complete_legacy(current_payload):
    store = RecordingJournalStore()
    state = make_state(None)
    config = make_config(store)
    current = invocation_scope(state, NODE, config)
    previous = old_scope(state, config)
    legacy = {"worker_result": {"current_requirements": "旧结果"}}
    store.rows[(RUN_ID, current)] = (3, deepcopy(current_payload))
    store.rows[(RUN_ID, previous)] = (9, deepcopy(legacy))
    observed = []

    async def worker(state, config):
        journal = current_worker_journal.get()
        observed.append((journal.scope_id, journal.version, journal.lease_token, deepcopy(journal.payload)))
        return {"current_requirements": "当前结果"}

    lease_token = current_execution_lease.set(LEASE)
    try:
        result = await with_worker_recovery(NODE, worker)(state, config)
    finally:
        current_execution_lease.reset(lease_token)

    assert result == {"current_requirements": "当前结果"}
    assert observed == [(current, 3, LEASE, current_payload)]
    assert store.loads == [(RUN_ID, current)]
    assert len(store.saves) == 1
    assert store.saves[0][:3] == (RUN_ID, current, 3)
    assert store.saves[0][4] == LEASE
    assert store.rows[(RUN_ID, current)] == (4, {**current_payload, "worker_result": result})
    assert store.rows[(RUN_ID, previous)] == (9, legacy)


@pytest.mark.parametrize(
    "submitted",
    [{}, {"party": {"adults": 1}}, {"party": {"adults": 2}}],
    ids=["empty-form", "one-adult", "two-adults"],
)
async def test_submitted_form_never_loads_or_replays_legacy(submitted):
    store = RecordingJournalStore()
    state = make_state(submitted)
    config = make_config(store)
    current = invocation_scope(state, NODE, config)
    previous = old_scope(state, config)
    legacy = {"worker_result": {"current_requirements": "旧结果"}}
    store.rows[(RUN_ID, previous)] = (4, deepcopy(legacy))
    observed = []

    async def worker(state, config):
        journal = current_worker_journal.get()
        observed.append((deepcopy(state.submitted_trip_identity), journal.scope_id, journal.version))
        return {"current_requirements": "表单对应的新结果"}

    result = await with_worker_recovery(NODE, worker)(state, config)

    assert current != previous
    assert result == {"current_requirements": "表单对应的新结果"}
    assert observed == [(submitted, current, 0)]
    assert store.loads == [(RUN_ID, current)]
    assert store.rows[(RUN_ID, previous)] == (4, legacy)
    assert store.rows[(RUN_ID, current)] == (1, {"worker_result": result})


async def test_null_empty_and_distinct_forms_have_isolated_results():
    store = RecordingJournalStore()
    config = make_config(store)
    states = [
        make_state(None),
        make_state({}),
        make_state({"party": {"adults": 1}}),
        make_state({"party": {"adults": 2}}),
    ]
    scopes = [invocation_scope(state, NODE, config) for state in states]
    assert len(set(scopes)) == len(states)
    assert len({old_scope(state, config) for state in states}) == 1
    previous = old_scope(states[0], config)
    legacy_result = {"current_requirements": "仅旧任务"}
    store.rows[(RUN_ID, previous)] = (2, {"worker_result": deepcopy(legacy_result)})
    calls = []

    async def worker(state, config):
        calls.append(deepcopy(state.submitted_trip_identity))
        return {"current_requirements": json.dumps(state.submitted_trip_identity, sort_keys=True)}

    recovered = with_worker_recovery(NODE, worker)
    results = [await recovered(state, config) for state in states]
    assert results[0] == legacy_result
    assert calls == [{}, {"party": {"adults": 1}}, {"party": {"adults": 2}}]
    assert len({result["current_requirements"] for result in results}) == len(states)
    assert [await recovered(state, config) for state in states] == results
    assert calls == [{}, {"party": {"adults": 1}}, {"party": {"adults": 2}}]
    assert (RUN_ID, scopes[0]) not in store.rows
    assert all((RUN_ID, scope) in store.rows for scope in scopes[1:])


async def test_old_task_only_recovers_itself_across_questions_answers_tasks_and_runs():
    store = RecordingJournalStore()
    config = make_config(store)
    original = make_state(
        understanding_qa=[{"question_id": "q-1", "answer": "青岛"}],
        understanding_rounds=1,
    )
    previous = old_scope(original, config)
    legacy = {"worker_result": {"current_requirements": "旧问答的结果"}}
    store.rows[(RUN_ID, previous)] = (5, deepcopy(legacy))
    variants = [
        (original.model_copy(update={"understanding_qa": [{"question_id": "q-1", "answer": "厦门"}]}), config),
        (original.model_copy(update={"understanding_qa": [{"question_id": "q-2", "answer": "青岛"}]}), config),
        (original, make_config(store, task_id="task-2")),
        (original.model_copy(update={"run_id": "run-other"}), config),
    ]
    calls = []

    async def worker(state, config):
        key = (state.run_id, deepcopy(state.understanding_qa), config["configurable"]["__pregel_task_id"])
        calls.append(key)
        return {"current_requirements": f"新任务-{len(calls)}"}

    recovered = with_worker_recovery(NODE, worker)
    assert await recovered(original, config) == legacy["worker_result"]
    results = []
    for state, variant_config in variants:
        before = len(store.loads)
        result = await recovered(state, variant_config)
        variant_current = invocation_scope(state, NODE, variant_config)
        variant_old = old_scope(state, variant_config)
        assert variant_old != previous
        assert store.loads[before:] == [(state.run_id, variant_current), (state.run_id, variant_old)]
        assert (state.run_id, variant_old) not in store.rows
        results.append(result)
    assert results == [{"current_requirements": f"新任务-{index}"} for index in range(1, 5)]
    assert len(calls) == 4
    assert await recovered(original, config) == legacy["worker_result"]
    assert [await recovered(state, variant_config) for state, variant_config in variants] == results
    assert len(calls) == 4
    assert store.rows[(RUN_ID, previous)][1] == legacy


async def test_missing_legacy_journal_runs_and_saves_current_scope():
    store = RecordingJournalStore()
    state = make_state()
    config = make_config(store)
    current = invocation_scope(state, NODE, config)
    previous = old_scope(state, config)
    calls = []

    async def worker(state, config):
        journal = current_worker_journal.get()
        calls.append((journal.scope_id, journal.version, journal.lease_token, deepcopy(journal.payload)))
        return {"current_requirements": "正常执行"}

    recovered = with_worker_recovery(NODE, worker)
    lease_token = current_execution_lease.set(LEASE)
    try:
        assert await recovered(state, config) == {"current_requirements": "正常执行"}
        assert await recovered(state, config) == {"current_requirements": "正常执行"}
    finally:
        current_execution_lease.reset(lease_token)

    assert calls == [(current, 0, LEASE, {})]
    assert store.loads == [(RUN_ID, current), (RUN_ID, previous), (RUN_ID, current)]
    assert [(save[1], save[2], save[4]) for save in store.saves] == [
        (current, 0, LEASE), (current, 1, LEASE)
    ]
    assert store.rows == {(RUN_ID, current): (2, {"worker_result": {"current_requirements": "正常执行"}})}


@pytest.mark.parametrize("complete", [True, False], ids=["complete", "partial"])
async def test_cancelled_run_does_not_replay_or_resume_legacy(complete):
    store = RecordingJournalStore()
    run_store = await make_run_store()
    state = make_state()
    config = make_config(store, run_store=run_store)
    current = invocation_scope(state, NODE, config)
    previous = old_scope(state, config)
    payload = (
        {"worker_result": {"controlled_trip_identity": {"origin": "旧结果"}}}
        if complete else {"understanding_react_0": {"phase": "request_started"}}
    )
    store.rows[(RUN_ID, previous)] = (4, deepcopy(payload))
    calls = []

    async def worker(state, config):
        calls.append(1)
        return {}

    handle = run_control_registry.register(RUN_ID)
    handle.request_stop("user_cancel")
    run_token = current_run_id.set(RUN_ID)
    try:
        with pytest.raises(RunCancelled) as exc:
            await with_worker_recovery(NODE, worker)(state, config)
    finally:
        current_run_id.reset(run_token)
        run_control_registry.unregister(RUN_ID, handle)

    assert exc.value.run_id == RUN_ID
    assert exc.value.node_name == NODE
    assert exc.value.reason == "user_cancel"
    assert calls == []
    assert store.loads == [(RUN_ID, current), (RUN_ID, previous)]
    assert store.saves == []
    assert store.rows == {(RUN_ID, previous): (4, payload)}
    assert (await run_store.get_run(RUN_ID)).controlled_trip_identity == {"origin": "原始出发地"}


@pytest.mark.parametrize("complete", [True, False], ids=["complete", "partial"])
@pytest.mark.parametrize("failure", ["lease", "cas"])
async def test_legacy_lease_and_cas_failures_propagate_without_retry(complete, failure, monkeypatch):
    store = RecordingJournalStore()
    run_store = await make_run_store()
    state = make_state()
    config = make_config(store, run_store=run_store)
    current = invocation_scope(state, NODE, config)
    previous = old_scope(state, config)
    payload = (
        {"worker_result": {"controlled_trip_identity": {"origin": "旧结果"}}}
        if complete else {"partial": {"step": 1}}
    )
    store.rows[(RUN_ID, previous)] = (5, deepcopy(payload))
    attempted = []
    original_save = store.save

    async def failing_save(run_id, scope_id, version, new_payload, *, lease_token=None):
        attempted.append((run_id, scope_id, version, lease_token))
        if failure == "lease":
            raise JournalConflict("worker journal execution lease lost")
        store.rows[(run_id, scope_id)] = (version + 1, {"owner": "other"})
        return await original_save(run_id, scope_id, version, new_payload, lease_token=lease_token)

    monkeypatch.setattr(store, "save", failing_save)
    calls = []

    async def worker(state, config):
        journal = current_worker_journal.get()
        calls.append((journal.scope_id, journal.version, journal.lease_token))
        journal.payload["partial"]["step"] = 2
        await journal.commit()
        return {"current_requirements": "不可见"}

    lease_token = current_execution_lease.set(LEASE)
    try:
        with pytest.raises(JournalConflict, match="lease lost" if failure == "lease" else "concurrent"):
            await with_worker_recovery(NODE, worker)(state, config)
    finally:
        current_execution_lease.reset(lease_token)

    assert calls == ([] if complete else [(previous, 5, LEASE)])
    assert attempted == [(RUN_ID, previous, 5, LEASE)]
    assert store.loads == [(RUN_ID, current), (RUN_ID, previous)]
    assert (RUN_ID, current) not in store.rows
    assert store.rows[(RUN_ID, previous)] == (
        (5, payload) if failure == "lease" else (6, {"owner": "other"})
    )
    assert (await run_store.get_run(RUN_ID)).controlled_trip_identity == {"origin": "原始出发地"}
    assert current_worker_journal.get() is None
