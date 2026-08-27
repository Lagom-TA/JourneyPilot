"""控制命令的判断规则：摘要口径、搬运与收口、协作边界的消费与去重。

**不需要 PostgreSQL**：这些是规则本身，一个假 store 就够。数据库那半（唯一约束、
`SKIP LOCKED`、结论不可改写）在 `tests/db/test_run_commands.py`。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

import pytest
from langgraph.errors import GraphInterrupt

from travel_agent.entities.trip_run import (
    RunCommand,
    RunCommandStatus,
    RunCommandType,
    TripRunStatus,
    generate_run_command_id,
    run_command_digest,
)
from travel_agent.entities.state import TravelAgentState
from travel_agent.entities.request_contract import (
    AmendmentImpact,
    IntentAmendmentRejection,
)
from travel_agent.services.run_commands import (
    PAST_SUPPLEMENT_STAGE,
    RUN_ENDED_BEFORE_CONSUMPTION,
    RunCommandCoordinator,
)
from travel_agent.workflows import run_control
from travel_agent.workflows.run_control import (
    RunCancelled,
    current_agent,
    current_model_window,
    current_node,
    current_run_budget,
    current_run_deadline,
    current_run_id,
    node_lifecycle_sink,
    run_control_registry,
    with_run_control,
)
from travel_agent.workflows.run_deadline import DeadlineObservation


def _capture_lifecycle() -> tuple[List[Dict[str, Any]], Any]:
    """挂一个收集 lifecycle 事件的 sink，返回 (事件列表, 还原用的 token)。"""

    events: List[Dict[str, Any]] = []

    async def sink(payload: Dict[str, Any]) -> None:
        events.append(payload)

    return events, node_lifecycle_sink.set(sink)


class FakeCommandStore:
    """内存版命令表。语义与 SQL 那份一致：只有未收口的命令能被取走或改写。"""

    def __init__(self) -> None:
        self.commands: Dict[str, RunCommand] = {}

    async def enqueue(
        self,
        run_id: str,
        command_type: str | RunCommandType,
        payload: Optional[Dict[str, Any]] = None,
    ) -> tuple[RunCommand, bool]:
        body = dict(payload or {})
        digest = run_command_digest(command_type, body)
        for command in self.commands.values():
            if command.run_id == run_id and command.request_digest == digest:
                return command, False
        command = RunCommand(
            command_id=generate_run_command_id(),
            run_id=run_id,
            command_type=command_type,
            payload=body,
            request_digest=digest,
        )
        self.commands[command.command_id] = command
        return command, True

    async def claim_pending(self, run_id: str, *, limit: int = 20) -> List[RunCommand]:
        claimed = []
        for command in list(self.commands.values()):
            if command.run_id != run_id or command.status is not RunCommandStatus.PENDING:
                continue
            command.status = RunCommandStatus.CLAIMED
            claimed.append(command)
        return claimed[:limit]

    async def settle(
        self,
        command_ids: Sequence[str],
        *,
        status: RunCommandStatus,
        result: Optional[Dict[str, Any]] = None,
        error_code: Optional[str] = None,
    ) -> int:
        settled = 0
        for command_id in command_ids:
            command = self.commands.get(command_id)
            if command is None or not command.is_open:
                continue
            command.status = status
            command.result = result
            command.error_code = error_code
            settled += 1
        return settled

    async def settle_open_for_run(
        self,
        run_id: str,
        *,
        status: RunCommandStatus,
        command_types=None,
        result: Optional[Dict[str, Any]] = None,
        error_code: Optional[str] = None,
    ) -> List[RunCommand]:
        kinds = (
            {RunCommandType(str(getattr(value, "value", value))) for value in command_types}
            if command_types is not None
            else set(RunCommandType)
        )
        settled = []
        for command in self.commands.values():
            if command.run_id != run_id or not command.is_open:
                continue
            if command.command_type not in kinds:
                continue
            command.status = status
            command.result = result
            command.error_code = error_code
            settled.append(command)
        return settled


class FakeTripRunStore:
    def __init__(self) -> None:
        self.events: List[tuple[str, str, Dict[str, Any]]] = []

    async def append_event_once(
        self,
        run_id: str,
        event_type: str,
        payload: Dict[str, Any],
        *,
        idempotency_key: str,
    ) -> None:
        if any(key == idempotency_key for _run, _type, key in self._keys()):
            return
        self.events.append((run_id, event_type, {**payload, "idempotency_key": idempotency_key}))

    def _keys(self):
        return [
            (run_id, event_type, payload.get("idempotency_key"))
            for run_id, event_type, payload in self.events
        ]


@pytest.fixture
def run_id() -> str:
    return "trip_commands"


@pytest.fixture
def wired(run_id):
    """一个已注册的 handle 加一个协调器，测试结束后清空进程内 registry。"""

    handle = run_control_registry.register(run_id)
    store = FakeCommandStore()
    runs = FakeTripRunStore()
    coordinator = RunCommandCoordinator(store, runs, run_id, handle, poll_seconds=0.2)
    try:
        yield handle, store, runs, coordinator
    finally:
        run_control_registry.clear()


def test_cancel_digest_ignores_payload_but_supplement_digest_does_not() -> None:
    """摘要口径就是幂等口径：取消按意图，追加要求按内容。"""

    assert run_command_digest(RunCommandType.CANCEL, {"source": "a"}) == run_command_digest(
        RunCommandType.CANCEL, {"source": "b"}
    )
    same = {"category": "food", "content": "少走路"}
    assert run_command_digest(
        RunCommandType.SUPPLEMENT, same
    ) == run_command_digest(RunCommandType.SUPPLEMENT, dict(same))
    assert run_command_digest(
        RunCommandType.SUPPLEMENT, same
    ) != run_command_digest(
        RunCommandType.SUPPLEMENT, {"category": "pace", "content": "少走路"}
    )


async def test_durable_cancel_reaches_the_boundary_without_any_notification(
    wired, run_id
) -> None:
    """进程内通知丢了也要停下来 —— 这正是命令落库的意义。"""

    handle, store, _runs, coordinator = wired
    await store.enqueue(run_id, RunCommandType.CANCEL, {"source": "control_api"})

    await coordinator.poll_once()

    assert handle.cancel_event.is_set()
    assert handle.stop_reason == "user_cancel"

    async def node(_state: TravelAgentState) -> Dict[str, Any]:  # pragma: no cover
        raise AssertionError("取消已经到达边界，节点不该被执行")

    with pytest.raises(RunCancelled):
        await with_run_control("planner", node)(
            TravelAgentState(run_id=run_id, user_message="x")
        )


async def test_supplement_is_consumed_only_after_contract_normalization(wired, run_id) -> None:
    handle, store, runs, coordinator = wired
    command, _ = await store.enqueue(
        run_id,
        RunCommandType.SUPPLEMENT,
        {"category": "food", "content": "想吃本地早餐"},
    )
    await coordinator.poll_once()

    async def node(state: TravelAgentState) -> Dict[str, Any]:
        assert [item.content for item in state.pending_intent_amendments] == [
            "想吃本地早餐"
        ]
        return {
            "pending_intent_amendments": [],
            "applied_intent_amendment_ids": [command.command_id],
            "intent_spec_revision": 2,
            "planning_generation": type(
                "Generation", (), {"generation_id": "generation_2"}
            )(),
        }

    update = await with_run_control("request_contract_normalizer", node)(
        TravelAgentState(run_id=run_id, user_message="x")
    )

    assert update["pending_intent_amendments"] == []
    assert update["applied_intent_amendment_ids"] == [command.command_id]
    assert store.commands[command.command_id].status is RunCommandStatus.CONSUMED
    assert store.commands[command.command_id].result == {
        "outcome": "applied",
        "applied_at_node": "request_contract_normalizer",
        "intent_spec_revision": 2,
        "generation_id": "generation_2",
    }
    assert [event_type for _run, event_type, _payload in runs.events] == [
        "run.supplement_applied"
    ]
    # 已经生效的要求不会在下一个节点边界再进一次 state。
    assert handle.pending_supplements() == []


async def test_a_failed_node_keeps_the_supplement_for_the_next_boundary(
    wired, run_id
) -> None:
    """节点抛异常时它的更新被丢掉，那条要求就没有生效，不许标成已消费。

    三值口径下这条路径落在 deferred 桶：applied 与 rejected 都是空集——库里
    保持 CLAIMED、result 未写、命令留在 handle 的 pending 列表里等下一个边界。
    随后的成功边界把它判进 applied 桶（CONSUMED），三个桶各就各位。
    """

    handle, store, _runs, coordinator = wired
    command, _ = await store.enqueue(
        run_id, RunCommandType.SUPPLEMENT, {"category": "pace", "content": "慢一点"}
    )
    await coordinator.poll_once()

    async def failing(_state: TravelAgentState) -> Dict[str, Any]:
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError):
        await with_run_control("planner", failing)(
            TravelAgentState(run_id=run_id, user_message="x")
        )

    assert [item["command_id"] for item in handle.pending_supplements()] == [
        command.command_id
    ]
    settled = store.commands[command.command_id]
    assert settled.status is RunCommandStatus.CLAIMED
    assert settled.result is None

    update = await with_run_control(
        "request_contract_normalizer",
        lambda state: {
            "pending_intent_amendments": [],
            "applied_intent_amendment_ids": [command.command_id],
        },
    )(
        TravelAgentState(run_id=run_id, user_message="x")
    )
    assert update["applied_intent_amendment_ids"] == [command.command_id]
    assert store.commands[command.command_id].status is RunCommandStatus.CONSUMED


async def test_divert_boundary_defers_every_read_command_without_touching_the_store(
    wired, run_id, caplog
) -> None:
    """divert 边界把命令搭进 state 等 router 下轮裁决：本轮既不 applied 也不 rejected，
    三值收口里它们落在 deferred 桶——一行日志把这说出口，库里状态不变。

    空 content 的命令本来更安静（连 fresh_amendments 都不进），现在同样被 deferred
    点名，不再无痕迹地消失。
    """

    handle, store, _runs, coordinator = wired
    live, _ = await store.enqueue(
        run_id,
        RunCommandType.SUPPLEMENT,
        {"category": "food", "content": "想吃本地早餐"},
    )
    blank, _ = await store.enqueue(
        run_id,
        RunCommandType.SUPPLEMENT,
        {"category": "food", "content": "   "},
    )
    await coordinator.poll_once()

    async def diverted(_state: TravelAgentState) -> Dict[str, Any]:  # pragma: no cover
        raise AssertionError("合同已建立且带新鲜 supplement 时应 divert，节点体不该执行")

    with caplog.at_level(logging.INFO, logger="travel_agent.workflows.run_control"):
        update = await with_run_control("planner", diverted)(
            TravelAgentState.model_construct(request_contract=object(), run_id=run_id)
        )

    # 节点体没跑：结果只有 resume_node 与搭车的 amendments（空内容那条进不来）。
    assert set(update) == {"intent_amendment_resume_node", "pending_intent_amendments"}
    assert [item.command_id for item in update["pending_intent_amendments"]] == [
        live.command_id
    ]
    # deferred 桶：两条命令都被日志点名，库里没有任何写发生。
    assert store.commands[live.command_id].status is RunCommandStatus.CLAIMED
    assert store.commands[blank.command_id].status is RunCommandStatus.CLAIMED
    assert store.commands[live.command_id].result is None
    assert [item["command_id"] for item in handle.pending_supplements()] == [
        live.command_id,
        blank.command_id,
    ]
    defer_logs = [
        record for record in caplog.records if "未产生判定" in record.getMessage()
    ]
    assert len(defer_logs) == 1
    message = defer_logs[0].getMessage()
    assert live.command_id in message and blank.command_id in message


async def test_router_rejection_settles_the_durable_supplement(wired, run_id) -> None:
    handle, store, runs, coordinator = wired
    command, _ = await store.enqueue(
        run_id,
        RunCommandType.SUPPLEMENT,
        {"category": "other", "content": "把目的地改成苏州"},
    )
    await coordinator.poll_once()

    async def reject(state: TravelAgentState) -> Dict[str, Any]:
        assert state.pending_intent_amendments[0].command_id == command.command_id
        return {
            "pending_intent_amendments": [],
            "rejected_intent_amendments": [
                IntentAmendmentRejection(
                    command_id=command.command_id,
                    impact=AmendmentImpact.IDENTITY_CHANGE,
                    reason_code="identity_change_requires_new_run",
                    requires_new_run=True,
                )
            ],
            "intent_amendment_route": "dispatcher",
        }

    await with_run_control("intent_amendment_router", reject)(
        TravelAgentState(run_id=run_id, user_message="x")
    )

    settled = store.commands[command.command_id]
    assert settled.status is RunCommandStatus.REJECTED
    assert settled.error_code == "identity_change_requires_new_run"
    assert settled.result["outcome"] == "rejected"
    assert settled.result["impact"] == "identity_change"
    assert settled.result["requires_new_run"] is True
    assert handle.pending_supplements() == []
    assert [event_type for _run, event_type, _payload in runs.events] == [
        "run.supplement_rejected"
    ]


async def test_a_replayed_supplement_does_not_enter_state_twice(wired, run_id) -> None:
    """命令至少消费一次：重复投递同一条要求不该让它在提示里出现两遍。"""

    handle, store, _runs, coordinator = wired
    command, _ = await store.enqueue(
        run_id, RunCommandType.SUPPLEMENT, {"category": "other", "content": "带孩子"}
    )
    await coordinator.poll_once()
    state = TravelAgentState(run_id=run_id, user_message="x")
    first = await with_run_control("planner", lambda s: {})(state)

    # 标记 consumed 之后崩溃、重启再投递一次：state 里已经有这个 command_id。
    handle.add_supplement("other", "带孩子", command_id=command.command_id)
    replayed_state = state.model_copy(
        update={"pending_intent_amendments": first["pending_intent_amendments"]}
    )
    second = await with_run_control("dispatcher", lambda s: {})(replayed_state)

    assert "pending_intent_amendments" not in second


async def test_supplement_after_delivery_is_rejected_not_left_pending(
    wired, run_id
) -> None:
    handle, store, _runs, coordinator = wired
    handle.mark_delivery_ready()
    command, _ = await store.enqueue(
        run_id, RunCommandType.SUPPLEMENT, {"category": "food", "content": "换一家"}
    )

    await coordinator.poll_once()

    settled = store.commands[command.command_id]
    assert settled.status is RunCommandStatus.REJECTED
    assert settled.error_code == PAST_SUPPLEMENT_STAGE
    assert handle.pending_supplements() == []


async def test_cancelled_run_consumes_its_cancel_and_rejects_the_rest(
    wired, run_id
) -> None:
    _handle, store, _runs, coordinator = wired
    cancel, _ = await store.enqueue(run_id, RunCommandType.CANCEL, {})
    supplement, _ = await store.enqueue(
        run_id, RunCommandType.SUPPLEMENT, {"category": "food", "content": "太晚了"}
    )

    await coordinator.settle_terminal(TripRunStatus.CANCELLED)

    assert store.commands[cancel.command_id].status is RunCommandStatus.CONSUMED
    assert store.commands[supplement.command_id].status is RunCommandStatus.REJECTED
    assert store.commands[supplement.command_id].error_code == RUN_ENDED_BEFORE_CONSUMPTION


async def test_a_completed_run_does_not_pretend_the_cancel_was_carried_out(
    wired, run_id
) -> None:
    """交付先提交、取消没赶上：那条取消**没有**被执行，回执要这么说。"""

    _handle, store, _runs, coordinator = wired
    cancel, _ = await store.enqueue(run_id, RunCommandType.CANCEL, {})

    await coordinator.settle_terminal(TripRunStatus.COMPLETED)

    settled = store.commands[cancel.command_id]
    assert settled.status is RunCommandStatus.REJECTED
    assert settled.error_code == RUN_ENDED_BEFORE_CONSUMPTION
    assert settled.result == {"run_status": TripRunStatus.COMPLETED.value}


def test_notification_is_only_a_wake_up(run_id) -> None:
    """registry 里没有 handle 不是拒绝：命令已经落库，通知只是少等一轮轮询。"""

    assert run_control_registry.notify(run_id) is False
    handle = run_control_registry.register(run_id)
    try:
        assert run_control_registry.notify(run_id) is True
        assert handle.wake_event.is_set()
    finally:
        run_control_registry.clear()


def test_parallel_workers_do_not_store_the_same_amendment_twice():
    """并行 Send 扇出里三个 worker 拿到同一份入参 state，都会判定这条要求还没并入。

    纯 append 的 reducer 会把它存下三份，此后每个下游提示里那句「本次运行追加要求」
    就出现三遍。
    """

    from travel_agent.entities.request_contract import IntentAmendment
    from travel_agent.entities.state import _replace_amendments

    amendment = IntentAmendment(
        command_id="cmd-1",
        category="food",
        content="清真",
        source_kind="run_supplement",
    )
    merged = _replace_amendments([], [amendment, amendment, amendment])

    assert merged == [amendment]


def test_replacing_amendments_keeps_order_and_distinct_commands():
    from travel_agent.entities.request_contract import IntentAmendment
    from travel_agent.entities.state import _replace_amendments

    first = IntentAmendment(
        command_id="cmd-1",
        category="other",
        content="a",
        source_kind="run_supplement",
    )
    second = IntentAmendment(
        command_id="cmd-2",
        category="other",
        content="b",
        source_kind="run_supplement",
    )

    assert _replace_amendments([first], [second, first]) == [second, first]


_ATTRIBUTION_VARS = (
    current_run_id,
    current_node,
    current_agent,
    current_run_deadline,
    current_run_budget,
    current_model_window,
)


def _attribution_values() -> Dict[Any, Any]:
    return {var: var.get() for var in _ATTRIBUTION_VARS}


def _assert_attribution_restored(before: Dict[Any, Any]) -> None:
    for var, value in before.items():
        assert var.get() == value


async def test_wrapped_node_restores_attribution_after_success(run_id) -> None:
    before = _attribution_values()

    update = await with_run_control("planner", lambda state: {"ok": True})(
        TravelAgentState(run_id=run_id, user_message="x")
    )

    assert update == {"ok": True}
    _assert_attribution_restored(before)


async def test_wrapped_node_restores_attribution_after_body_failure(run_id) -> None:
    before = _attribution_values()

    async def failing(_state: TravelAgentState) -> Dict[str, Any]:
        raise RuntimeError("node body exploded")

    with pytest.raises(RuntimeError):
        await with_run_control("planner", failing)(
            TravelAgentState(run_id=run_id, user_message="x")
        )

    _assert_attribution_restored(before)


async def test_wrapped_node_restores_attribution_when_binding_fails(
    run_id, monkeypatch
) -> None:
    def exploded_window(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("model window binding exploded")

    def exploded_ts() -> Any:
        raise RuntimeError("run_ts_ms binding exploded")

    for target, exploded in (
        ("_model_window_for_node", exploded_window),
        ("run_ts_ms", exploded_ts),
    ):
        before = _attribution_values()
        monkeypatch.setattr(run_control, target, exploded)
        with pytest.raises(RuntimeError):
            await with_run_control("planner", lambda state: {})(
                TravelAgentState(run_id=run_id, user_message="x")
            )
        _assert_attribution_restored(before)
        monkeypatch.undo()


async def test_wrapped_node_restores_deadline_overwritten_by_bare_set(run_id) -> None:
    sentinel_a = object()
    sentinel_b = object()
    token = current_run_deadline.set(sentinel_a)
    try:
        async def node(_state: TravelAgentState) -> Dict[str, Any]:
            current_run_deadline.set(sentinel_b)
            return {}

        await with_run_control("planner", node)(
            TravelAgentState(run_id=run_id, user_message="x")
        )

        assert current_run_deadline.get() is sentinel_a
    finally:
        current_run_deadline.reset(token)


async def test_worker_entering_after_delivery_is_ignored_without_any_lifecycle_event(
    wired, run_id
) -> None:
    """交付已经落库才被调度的 worker 在进入前就被拦下：不执行、不发任何事件。"""

    handle, _store, _runs, _coordinator = wired
    handle.mark_delivery_ready()

    events, token = _capture_lifecycle()
    try:

        async def late_worker(_state: TravelAgentState) -> Dict[str, Any]:  # pragma: no cover
            raise AssertionError("交付之后 worker 不该再被执行")

        update = await with_run_control("destination_researcher", late_worker)(
            TravelAgentState(run_id=run_id, user_message="x")
        )
    finally:
        node_lifecycle_sink.reset(token)

    assert update == {
        "run_deadline": None,
        "agent_status": {"destination_researcher": "ignored_after_delivery"},
    }
    assert events == []


async def test_a_worker_returning_after_delivery_is_overwritten_but_still_reports_completed(
    wired, run_id
) -> None:
    """finalizer 在 worker 返回途中赢了：更新被丢弃，但节点确实跑完了，completed 照发。"""

    handle, _store, _runs, _coordinator = wired
    events, token = _capture_lifecycle()
    try:

        async def losing_worker(_state: TravelAgentState) -> Dict[str, Any]:
            # 模拟另一个协程在 worker 执行期间完成了交付。
            handle.mark_delivery_ready()
            return {
                "applied_intent_amendment_ids": ["cmd-late-1"],
                "agent_status": {"destination_researcher": "completed"},
            }

        update = await with_run_control("destination_researcher", losing_worker)(
            TravelAgentState(run_id=run_id, user_message="x")
        )
    finally:
        node_lifecycle_sink.reset(token)

    assert update == {
        "run_deadline": None,
        "agent_status": {"destination_researcher": "ignored_after_delivery"},
    }
    assert [event["status"] for event in events] == ["started", "completed"]


async def test_delivery_finalizer_marks_the_handle_delivery_ready(wired, run_id) -> None:
    """唯一置位 delivery_ready 的路径：finalizer 报告 delivery_persisted=True。"""

    handle, _store, _runs, _coordinator = wired
    assert not handle.delivery_ready_event.is_set()

    async def finalizer(_state: TravelAgentState) -> Dict[str, Any]:
        return {"delivery_persisted": True}

    await with_run_control("delivery_finalizer", finalizer)(
        TravelAgentState(run_id=run_id, user_message="x")
    )

    assert handle.delivery_ready_event.is_set()


async def test_graph_interrupt_passes_through_the_wrapper_untouched(wired, run_id) -> None:
    """plan_gate 的 interrupt 靠包装层原样放行才能落进 checkpoint：不算失败。"""

    _handle, _store, _runs, _coordinator = wired
    events, token = _capture_lifecycle()
    try:

        async def gating(_state: TravelAgentState) -> Dict[str, Any]:
            raise GraphInterrupt()

        with pytest.raises(GraphInterrupt):
            await with_run_control("plan_gate", gating)(
                TravelAgentState(run_id=run_id, user_message="x")
            )
    finally:
        node_lifecycle_sink.reset(token)

    # started 已发；重抛发生在 failed/completed 之前，两者都不许出现。
    assert [event["status"] for event in events] == ["started"]


def test_blocked_research_worker_update_shape() -> None:
    """窗口关闭时挡住 worker 的返回结构：过期相位写 failed + last_error，其余写 partial。

    dispatcher 靠这两个 agent_status 推进计划（`partial`/`failed` 是终态值），错误文案
    区分 research worker 与 itinerary 组合两条路径。
    """

    observed = object()
    research_phase = DeadlineObservation(
        elapsed_seconds=100.0, remaining_seconds=0.0, phase="closeout"
    )

    blocked = run_control._blocked_research_worker_update(
        node_name="transport_researcher",
        observed_deadline=observed,
        observation=research_phase,
    )
    assert blocked == {
        "run_deadline": observed,
        "agent_status": {"transport_researcher": "partial"},
    }

    expired_research = DeadlineObservation(
        elapsed_seconds=500.0, remaining_seconds=-10.0, phase="expired"
    )
    failed = run_control._blocked_research_worker_update(
        node_name="transport_researcher",
        observed_deadline=observed,
        observation=expired_research,
    )
    assert failed["run_deadline"] is observed
    assert failed["agent_status"] == {"transport_researcher": "failed"}
    assert failed["last_error"] == (
        "delivery deadline elapsed before research worker could start"
    )

    expired_composition = run_control._blocked_research_worker_update(
        node_name="itinerary_planner",
        observed_deadline=observed,
        observation=expired_research,
    )
    assert expired_composition["last_error"] == (
        "delivery deadline elapsed before itinerary composition"
    )
