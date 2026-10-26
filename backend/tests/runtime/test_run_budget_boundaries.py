"""预算耗尽在两条调用边界上的收口方式，以及封存不变量。"""

from __future__ import annotations

import pytest

from tests.fixtures.planning_state import make_minimum_draft
from travel_agent.runtime.budget import (
    RunBudgetExhausted,
    RunBudgetSnapshot,
    ledger_for,
    reset_ledgers,
)
from travel_agent.runtime.context import current_run_budget, current_run_id
from travel_agent.tools.execution import execute_tool


@pytest.fixture(autouse=True)
def _isolate_ledgers():
    reset_ledgers()
    yield
    reset_ledgers()


def _snapshot(**overrides) -> RunBudgetSnapshot:
    payload = dict(
        enforce_limits=True,
        max_llm_calls=10,
        max_tool_calls=1,
        max_input_tokens=10_000,
        max_output_tokens=1_000,
        max_cost_usd=1.0,
        max_tool_retries_per_target=0,
    )
    payload.update(overrides)
    return RunBudgetSnapshot(**payload)


async def test_tool_call_over_budget_returns_a_failed_envelope_not_an_exception():
    """把「配额用完了」抛成异常会变成一次 Run 失败。

    它实际是一次可解释的降级：Worker 拿到普通的 failed envelope，把内容缺口交给后续
    交付流程，与研究窗口关闭时使用同一处理路径。
    """

    snapshot = _snapshot(max_tool_calls=1)
    token_run = current_run_id.set("run_tool_budget")
    token_budget = current_run_budget.set(snapshot)
    try:
        ledger = ledger_for("run_tool_budget", snapshot)
        ledger.record_tool_call("web_search")
        envelope = await execute_tool("web_search", {"query": "京都"})
    finally:
        current_run_budget.reset(token_budget)
        current_run_id.reset(token_run)

    assert envelope["status"] == "failed"
    assert envelope["error"] == "run_budget_exhausted.tool_calls"
    assert envelope["metadata"]["run_budget_exhausted"] == "tool_calls"


async def test_a_tool_that_used_up_its_retries_is_not_called_again():
    snapshot = _snapshot(max_tool_calls=50, max_tool_retries_per_target=1)
    token_run = current_run_id.set("run_tool_retries")
    token_budget = current_run_budget.set(snapshot)
    try:
        ledger = ledger_for("run_tool_retries", snapshot)
        ledger.record_tool_retry("web_search")
        envelope = await execute_tool("web_search", {"query": "京都"})
    finally:
        current_run_budget.reset(token_budget)
        current_run_id.reset(token_run)

    assert envelope["status"] == "failed"
    assert envelope["metadata"]["tool_retries_exhausted"] == "web_search"




def _generation():
    from travel_agent.planning.requirements.generation_contracts import (
        PlanningGeneration,
    )

    return PlanningGeneration(
        generation_id="generation_budget",
        controlled_trip_identity_revision=1,
        intent_spec_revision=1,
        constraint_pack_revision=0,
        plan_revision=0,
        identity_hash="2" * 64,
        intent_hash="1" * 64,
        constraint_hash="3" * 64,
    )


def _intent_spec():
    from travel_agent.planning.requirements.intent_contracts import IntentSpec

    return IntentSpec(
        intent_spec_id="intent_spec_budget",
        revision=1,
        generation_id="generation_budget",
        content_hash="1" * 64,
        objective_summary="预算边界测试",
    )


def test_budget_and_deadline_must_be_sealed_together():
    """一个封了 Deadline 却没有预算的 Run 说明有条路径只封了一半。"""

    from travel_agent.planning.delivery.minimum_draft import seal_minimum_delivery_draft
    from travel_agent.planning.state import TravelAgentState

    class _State:
        minimum_delivery_draft = make_minimum_draft()
        run_deadline = None
        run_budget = None

    sealed = seal_minimum_delivery_draft(_State())
    with pytest.raises(ValueError, match="sealed together"):
        TravelAgentState(
            session_id="s",
            run_id="run_seal_budget",
            controlled_trip_identity_revision=1,
            intent_spec_revision=1,
            intent_spec=_intent_spec(),
            planning_generation=_generation(),
            minimum_delivery_draft=sealed["minimum_delivery_draft"],
            run_deadline=sealed["run_deadline"],
        )


def test_sealing_a_draft_produces_a_budget_alongside_the_deadline():
    from travel_agent.planning.delivery.minimum_draft import seal_minimum_delivery_draft

    class _State:
        minimum_delivery_draft = make_minimum_draft()
        run_deadline = None
        run_budget = None

    update = seal_minimum_delivery_draft(_State())
    assert update["run_deadline"] is not None
    assert update["run_budget"] is not None
    assert update["run_budget"].policy_version == "run_budget.v1"


def test_a_replay_of_a_sealed_draft_never_refills_the_budget():
    """重放已封存的一代不许换来一份新预算 —— 那等于给 Run 续一次费。"""

    from travel_agent.planning.delivery.minimum_draft import seal_minimum_delivery_draft

    class _State:
        minimum_delivery_draft = make_minimum_draft()
        run_deadline = None
        run_budget = None

    first = seal_minimum_delivery_draft(_State())

    class _Replayed:
        minimum_delivery_draft = first["minimum_delivery_draft"]
        run_deadline = first["run_deadline"]
        run_budget = first["run_budget"]

    second = seal_minimum_delivery_draft(_Replayed())
    assert second["run_budget"] is first["run_budget"]
    assert second["run_deadline"] is first["run_deadline"]


def test_clearing_a_draft_generation_clears_the_budget_too():
    from travel_agent.planning.delivery.minimum_draft import (
        _clear_completion_generation,
    )

    cleared = _clear_completion_generation()
    assert cleared["run_deadline"] is None
    assert cleared["run_budget"] is None
    assert "run_budget" in cleared


async def test_the_retry_loop_cannot_outspend_the_tool_call_budget():
    """入口只判一次「还剩一次调用」时，循环里仍可能记满 max_retries + 1 次再加一次降级。

    判与记是两个可以分别调用的函数，漏掉判的那一半不会报错，只会让 max_tool_calls
    的约束被放大数倍。这一条要求每次尝试都先判一次。
    """

    snapshot = _snapshot(max_tool_calls=2, max_tool_retries_per_target=5)
    token_run = current_run_id.set("run_retry_spend")
    token_budget = current_run_budget.set(snapshot)
    try:
        ledger = ledger_for("run_retry_spend", snapshot)
        ledger.reserve_tool_call("tool.web_search", "web_search")
        ledger.reserve_tool_call("tool.web_search", "web_search")
        # 预算已经用满：第三次预留必须被拒，而不是记进去再说。
        with pytest.raises(RunBudgetExhausted):
            ledger.reserve_tool_call("tool.web_search", "web_search")
    finally:
        current_run_budget.reset(token_budget)
        current_run_id.reset(token_run)

    assert ledger.usage().tool_calls == 2


async def test_usage_flush_stops_volatile_recovery_after_first_io_failure(monkeypatch):
    from unittest.mock import Mock

    from travel_agent.llm.usage import LLMCallRecord, UsageRecorder
    from travel_agent.runtime.usage_flush import UsageFlushService
    from travel_agent.storage.cost_ledger_store import InMemoryCostLedgerStore

    recorder = UsageRecorder(maxlen=2)
    put = recorder._spool.put
    failing_put = Mock(side_effect=OSError("disk full"))
    monkeypatch.setattr(recorder._spool, "put", failing_put)
    records = [LLMCallRecord(
        id=f"call-{n}", run_id="run", node=None, agent=None, tier="fast",
        provider="test", model_request="test", method="ainvoke", stream=False,
        start_ts="2026-10-08T00:00:00+00:00",
        input_tokens=10, output_tokens=5, total_tokens=15,
    ) for n in range(7)]
    for rec in records:
        recorder.record(rec)
    recover = Mock(wraps=recorder._spool.recover_abandoned)
    monkeypatch.setattr(recorder._spool, "recover_abandoned", recover)

    class Unavailable:
        async def record_calls(self, batch):
            raise ConnectionError("cost database unavailable")

    service = UsageFlushService(recorder, Unavailable())
    for _ in range(3):
        failing_put.reset_mock()
        await service.flush()
        assert failing_put.call_count == 1
        recover.assert_not_called()
        assert list(recorder._volatile.values()) == [("complete", rec) for rec in records]
        assert recorder.integrity("run")["spool_write_failed"] == len(records)

    monkeypatch.setattr(recorder._spool, "put", put)
    service.store = InMemoryCostLedgerStore()
    await service.flush()
    assert [call.id for call in service.store.calls] == [rec.id for rec in records]
    assert recorder.drain() == [] and recorder._volatile == {}
    assert recorder.integrity("run")["pending_call_count"] == 0
    assert recorder.integrity("run")["spool_write_failed"] == len(records)


def test_usage_drain_limits_volatile_recovery_to_batch_size(monkeypatch):
    from unittest.mock import Mock

    from travel_agent.llm.usage import LLMCallRecord, UsageRecorder

    recorder = UsageRecorder(maxlen=2)
    put = recorder._spool.put
    monkeypatch.setattr(recorder._spool, "put", Mock(side_effect=OSError("disk full")))
    for n in range(7):
        recorder.record(LLMCallRecord(
            id=f"call-{n}", run_id="run", node=None, agent=None, tier="fast",
            provider="test", model_request="test", method="ainvoke", stream=False,
            start_ts="2026-10-08T00:00:00+00:00",
        ))
    recovering_put = Mock(wraps=put)
    monkeypatch.setattr(recorder._spool, "put", recovering_put)
    for expected_volatile, expected_attempts in [(5, 2), (3, 2), (1, 2), (0, 1)]:
        recovering_put.reset_mock()
        recorder.drain()
        assert recovering_put.call_count == expected_attempts
        assert len(recorder._volatile) == expected_volatile
    assert {data["id"] for data in recorder._spool.pending()} == {
        f"call-{n}" for n in range(7)
    }


def test_usage_spool_excludes_poison_ids_before_applying_limit():
    from travel_agent.llm.usage import LLMCallRecord, UsageRecorder

    recorder = UsageRecorder(maxlen=1)
    poison_id = "poison'); DROP TABLE usage_outbox; --"
    for call_id in [poison_id, "healthy"]:
        recorder.record(LLMCallRecord(
            id=call_id, run_id="run", node=None, agent=None, tier="fast",
            provider="test", model_request="test", method="ainvoke", stream=False,
            start_ts="2026-10-08T00:00:00+00:00",
        ))
    assert [data["id"] for data in recorder._spool.pending(
        run_id="run", limit=1, exclude_ids={poison_id}
    )] == ["healthy"]
    assert recorder._spool.integrity("run") == (2, 0)


@pytest.mark.parametrize("batch_size", [1, 3])
def test_usage_drain_stops_retrying_shared_io_failure_without_losing_records(
    tmp_path, monkeypatch, batch_size
):
    from travel_agent.llm.usage import LLMCallRecord, UsageRecorder

    recorder = UsageRecorder(maxlen=batch_size, spool_path=tmp_path / "spool.sqlite3")
    attempts = []

    def unavailable(payload, **kwargs):
        attempts.append(payload["id"])
        raise OSError("disk full")

    monkeypatch.setattr(recorder._spool, "put", unavailable)
    records = [
        LLMCallRecord(
            id=f"call-{n}", run_id="run", node=None, agent=None, tier="fast",
            provider="test", model_request="test", method="ainvoke", stream=False,
            start_ts="2026-10-08T00:00:00+00:00",
        )
        for n in range(7)
    ]
    for rec in records:
        recorder.record(rec)
    monkeypatch.setattr(
        recorder._spool, "recover_abandoned",
        lambda: pytest.fail("shared write failure must stop further write attempts"),
    )
    for _ in range(3):
        attempts.clear()
        assert recorder.drain() == records
        assert len(attempts) == 1
        assert len(recorder._volatile) == len(records)
        integrity = recorder.integrity("run")
        assert integrity["spool_write_failed"] == len(records)
        assert integrity["pending_call_count"] == len(records)
        assert not integrity["capture_complete"]
    recorder._spool.db.close()


@pytest.mark.parametrize("batch_size", [1, 3])
def test_usage_drain_bounds_successful_local_recovery_attempts(
    tmp_path, monkeypatch, batch_size
):
    from travel_agent.llm.usage import LLMCallRecord, UsageRecorder

    recorder = UsageRecorder(maxlen=batch_size, spool_path=tmp_path / "spool.sqlite3")
    put = recorder._spool.put

    def unavailable(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(recorder._spool, "put", unavailable)
    records = [
        LLMCallRecord(
            id=f"call-{n}", run_id="run", node=None, agent=None, tier="fast",
            provider="test", model_request="test", method="ainvoke", stream=False,
            start_ts="2026-10-08T00:00:00+00:00",
        )
        for n in range(7)
    ]
    for rec in records:
        recorder.record(rec)
    attempts = []

    def recovered(payload, **kwargs):
        attempts.append(payload["id"])
        return put(payload, **kwargs)

    monkeypatch.setattr(recorder._spool, "put", recovered)
    assert {rec.id for rec in recorder.drain()} == {rec.id for rec in records}
    assert len(attempts) == batch_size
    assert len(recorder._volatile) == len(records) - batch_size
    assert len(recorder._spool.pending()) == batch_size
    recorder._spool.db.close()
