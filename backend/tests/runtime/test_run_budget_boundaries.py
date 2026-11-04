"""预算耗尽在两条调用边界上的收口方式，以及封存不变量。"""

from __future__ import annotations

import asyncio

import pytest

from tests.fixtures.planning_state import make_minimum_draft
from tests.support.memory_stores import InMemoryWorkerJournalStore
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




async def test_parallel_model_reservations_wait_for_actual_usage():
    ledger = ledger_for("parallel-model", _snapshot(max_llm_calls=2, max_output_tokens=100))
    first_started = asyncio.Event()
    release = asyncio.Event()
    second_started = asyncio.Event()

    async def first():
        async with ledger.reserve_model("first", input_tokens=1, output_tokens=80):
            first_started.set()
            await release.wait()
            ledger.record_llm_call(input_tokens=1, output_tokens=10, cost_usd=0)

    async def second():
        async with ledger.reserve_model("second", input_tokens=1, output_tokens=80):
            second_started.set()
            ledger.record_llm_call(input_tokens=1, output_tokens=10, cost_usd=0)

    task = asyncio.create_task(first())
    await first_started.wait()
    waiting = asyncio.create_task(second())
    await asyncio.sleep(0)
    assert not second_started.is_set()
    release.set()
    await asyncio.gather(task, waiting)
    assert second_started.is_set() and ledger.usage().llm_calls == 2
    assert ledger.pending_llm_calls == 0


async def test_parallel_model_reservations_include_estimated_cost():
    ledger = ledger_for("parallel-cost", _snapshot(max_cost_usd=1.0))
    admitted = asyncio.Event()
    release = asyncio.Event()

    async def first():
        async with ledger.reserve_model(
            "first", input_tokens=1, output_tokens=1, estimated_cost_usd=0.6,
        ):
            admitted.set()
            await release.wait()
            ledger.record_llm_call(input_tokens=1, output_tokens=1, cost_usd=0.6)

    async def second():
        async with ledger.reserve_model(
            "second", input_tokens=1, output_tokens=1, estimated_cost_usd=0.6,
        ):
            pytest.fail("预估费用超限时不得发起第二次调用")

    running = asyncio.create_task(first())
    await admitted.wait()
    waiting = asyncio.create_task(second())
    await asyncio.sleep(0)
    assert not waiting.done()
    release.set()
    await running
    with pytest.raises(RunBudgetExhausted) as exc:
        await waiting
    assert exc.value.dimension == "cost_usd"
    assert ledger.pending_cost_usd == pytest.approx(0)


async def test_tool_budget_persists_across_ledger_recreation():
    from travel_agent.runtime.journal import WorkerJournal, current_worker_journal
    from travel_agent.tools.execution import _reserve_tool_budget

    store = InMemoryWorkerJournalStore()
    journal = WorkerJournal(store, "run", "worker", 0, {}, None)
    token = current_worker_journal.set(journal)
    snapshot = _snapshot(max_tool_calls=1)
    try:
        await _reserve_tool_budget(ledger_for("run", snapshot), "run", "search")
        reset_ledgers()
        with pytest.raises(RunBudgetExhausted, match="run budget exhausted"):
            await _reserve_tool_budget(ledger_for("run", snapshot), "run", "search")
    finally:
        current_worker_journal.reset(token)


async def test_parallel_tool_reservations_enforce_limit_and_isolate_runs():
    from travel_agent.storage.worker_journal_store import TOOL_BUDGET_SCOPE

    store = InMemoryWorkerJournalStore()
    reservations = await asyncio.gather(*(
        store.reserve_tool("run", "search", lease_token=None, limit=3, retry=True)
        for _ in range(10)
    ))
    accepted = [item for item in reservations if item is not None]
    assert len(accepted) == 3
    assert sorted(item["calls"] for item in accepted) == [1, 2, 3]
    assert await store.load("run", TOOL_BUDGET_SCOPE) == (
        4, {"calls": 3, "retries": {"search": 3}},
    )

    # 返回值不能持有仓储内部的引用；其他 Run 也有独立预算。
    accepted[0]["retries"]["search"] = 100
    assert await store.load("run", TOOL_BUDGET_SCOPE) == (
        4, {"calls": 3, "retries": {"search": 3}},
    )
    assert await store.reserve_tool("other-run", "search", limit=3) == {
        "calls": 1, "retries": {},
    }


def _generation():
    from travel_agent.planning.requirements.generation_contracts import (
        PlanningGeneration,
    )

    return PlanningGeneration(generation_id="generation_budget", revision=1)


def test_budget_and_deadline_must_be_sealed_together():
    """一个封了 Deadline 却没有预算的 Run 说明有条路径只封了一半。"""

    from travel_agent.planning.delivery.minimum_draft import seal_minimum_delivery_draft
    from travel_agent.planning.state import TravelAgentState

    class _State:
        minimum_delivery_draft = make_minimum_draft()
        run_deadline = None
        run_budget = None

    sealed = seal_minimum_delivery_draft(_State())
    with pytest.raises(ValueError, match="必须同时存在"):
        TravelAgentState(
            session_id="s",
            run_id="run_seal_budget",
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
    assert "policy_version" not in update["run_budget"].model_dump()


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


async def test_the_retry_loop_cannot_outspend_the_tool_call_budget(monkeypatch):
    """重试循环每次尝试都要先过预算闸，而不是入口判一次、循环里只记账。

    入口只判一次「还剩一次调用」时，循环里仍可能记满 max_retries + 1 次再加一次降级；
    判与记是两个可以分别调用的函数，漏掉判的那一半不会报错，只会让 max_tool_calls
    的约束被放大数倍。这一条用真实的 execute_tool 重试循环驱动：前两次尝试耗尽
    调用预算，第三次尝试必须被闸在预算上，而不是真的发起。
    """

    from travel_agent.tools import execution as execution_module
    from travel_agent.tools.registry import ToolRegistry

    snapshot = _snapshot(max_tool_calls=2, max_tool_retries_per_target=5)
    token_run = current_run_id.set("run_retry_spend")
    token_budget = current_run_budget.set(snapshot)
    try:
        ledger = ledger_for("run_retry_spend", snapshot)
        registry = ToolRegistry()
        attempts: list[str] = []

        async def flaky(**kwargs):
            attempts.append("web_search")
            return {"success": False, "error": "connection reset by provider"}

        registry.register(
            "web_search", "search the web", {"type": "object", "properties": {}},
            flaky, source="local",
        )
        monkeypatch.setattr(execution_module, "get_tool_registry", lambda: registry)
        result = await execute_tool(
            "web_search", {"query": "京都"}, max_retries=3,
        )
        # 前两次尝试真实发起，第三次被预算闸拒绝后以 failed 信封返回。
        assert attempts == ["web_search", "web_search"]
        assert result["status"] == "failed"
        assert result["metadata"]["run_budget_exhausted"] == "tool_calls"
        assert ledger.usage().tool_calls == 2
        assert ledger.tool_retries == {"web_search": 1}
    finally:
        current_run_budget.reset(token_budget)
        current_run_id.reset(token_run)
