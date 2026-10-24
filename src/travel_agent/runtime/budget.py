from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional, get_args
from pydantic import Field
from travel_agent.schema import StrictModel
from ..config import get_settings
from .context import current_run_budget, current_run_id


RUN_BUDGET_POLICY_VERSION = "run_budget.v1"


BudgetDimension = Literal[
    "llm_calls",
    "tool_calls",
    "input_tokens",
    "output_tokens",
    "cost_usd",
]


BUDGET_DIMENSIONS: tuple[BudgetDimension, ...] = get_args(BudgetDimension)


class RunBudgetSnapshot(StrictModel):
    """Run 授权时封存的上限。跨进程的最终事实，随 checkpoint 一起走。"""

    policy_version: str = RUN_BUDGET_POLICY_VERSION
    # Missing in old checkpoints means observation only, so resumed runs also
    # stop inheriting the former implicit quotas.
    enforce_limits: bool = False
    max_llm_calls: Optional[int] = Field(default=None, ge=1)
    max_tool_calls: Optional[int] = Field(default=None, ge=1)
    max_input_tokens: Optional[int] = Field(default=None, ge=1)
    max_output_tokens: Optional[int] = Field(default=None, ge=1)
    max_cost_usd: Optional[float] = Field(default=None, gt=0)
    max_tool_retries_per_target: Optional[int] = Field(default=None, ge=0)

    def limit(self, dimension: BudgetDimension) -> Optional[float]:
        value = getattr(self, f"max_{dimension}")
        return None if value is None else float(value)


class RunBudgetUsage(StrictModel):
    """已经花掉的量。

    ``cost_complete`` 说的是「这个费用数字能不能当上限用」：价格表没命中的调用只报
    token、不编造成本（`cost_ledger_store.compute_cost_usd` 返回 None），于是费用
    这一维会低报。低报的上限不许拦人 —— 见 `exhausted_dimension`。
    """

    llm_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)
    cost_complete: bool = True

    def spent(self, dimension: BudgetDimension) -> float:
        return float(getattr(self, dimension))


def remaining_budget(
    snapshot: RunBudgetSnapshot, usage: RunBudgetUsage
) -> Dict[str, Optional[float]]:
    """每一维还剩多少。负数被夹到 0：已经超了就是没有了。"""

    return {
        dimension: (
            max(0.0, snapshot.limit(dimension) - usage.spent(dimension))
            if snapshot.enforce_limits and snapshot.limit(dimension) is not None
            else None
        )
        for dimension in BUDGET_DIMENSIONS
    }


def exhausted_dimension(
    snapshot: RunBudgetSnapshot,
    usage: RunBudgetUsage,
    *,
    llm_calls: int = 0,
    tool_calls: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> Optional[BudgetDimension]:
    """按「这次最坏花多少」判还能不能再发一次调用。

    参数是**本次调用的最坏开销预估**，不是已消耗量。只在调用后记账不能阻止超支：
    第 101 次调用之后再发现超了 100 次上限，那 101 次已经花掉了。

    费用这一维在 ``cost_complete=False`` 时不参与判定：价格表没命中的调用让费用低报，
    而一个低报的读数拦不住真正的超支，却会在别处误伤。低报这件事本身由
    ``cost_complete`` 报出去（readiness / 成本摘要），不在这里假装成一个上限。
    """

    if not snapshot.enforce_limits:
        return None
    projected = {
        "llm_calls": usage.llm_calls + llm_calls,
        "tool_calls": usage.tool_calls + tool_calls,
        "input_tokens": usage.input_tokens + input_tokens,
        "output_tokens": usage.output_tokens + output_tokens,
        "cost_usd": usage.cost_usd,
    }
    for dimension in BUDGET_DIMENSIONS:
        if dimension == "cost_usd" and not usage.cost_complete:
            continue
        limit = snapshot.limit(dimension)
        if limit is not None and projected[dimension] > limit:
            return dimension
    return None


logger = logging.getLogger(__name__)


class RunBudgetExhausted(RuntimeError):
    """一次新调用会越过预算的某一维。

    和 `ModelWindowClosed` 同一类：**用户没有取消**，所以调用方必须走确定性收口，
    不能把它记成 CANCELLED。区别在 reason code —— 时间用完和钱用完不是同一件事。
    """

    def __init__(
        self,
        operation: str,
        dimension: BudgetDimension,
        snapshot: RunBudgetSnapshot,
        usage: RunBudgetUsage,
    ) -> None:
        self.operation = operation
        self.dimension = dimension
        self.snapshot = snapshot
        self.usage = usage
        super().__init__(
            f"run budget exhausted on {dimension} before {operation} "
            f"(spent={usage.spent(dimension)}, limit={snapshot.limit(dimension)})"
        )

    @property
    def reason_code(self) -> str:
        return f"run_budget_exhausted.{self.dimension}"


def build_run_budget_snapshot(
    *, policy_version: str = RUN_BUDGET_POLICY_VERSION
) -> RunBudgetSnapshot:
    """按当前配置封存一份上限。只在 Run 被授权时调用一次。"""

    config = get_settings().run_budget
    return RunBudgetSnapshot(
        policy_version=policy_version,
        enforce_limits=config.enforce_limits,
        max_llm_calls=config.max_llm_calls,
        max_tool_calls=config.max_tool_calls,
        max_input_tokens=config.max_input_tokens,
        max_output_tokens=config.max_output_tokens,
        max_cost_usd=config.max_cost_usd,
        max_tool_retries_per_target=config.max_tool_retries_per_target,
    )


@dataclass
class RunBudgetLedger:
    """一个 Run 在本进程的消耗账本。"""

    run_id: str
    snapshot: RunBudgetSnapshot
    llm_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    #: 有没有出现过价格表没命中的调用。见 `RunBudgetUsage.cost_complete`。
    unpriced_calls: int = 0
    #: 每个工具在这个 Run 上**重试**了多少轮。首次调用不计在内。
    tool_retries: Dict[str, int] = field(default_factory=dict)
    seeded: bool = False

    def usage(self) -> RunBudgetUsage:
        return RunBudgetUsage(
            llm_calls=self.llm_calls,
            tool_calls=self.tool_calls,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cost_usd=round(self.cost_usd, 8),
            cost_complete=self.unpriced_calls == 0,
        )

    def guard(
        self,
        operation: str,
        *,
        llm_calls: int = 0,
        tool_calls: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        usage = self.usage()
        dimension = exhausted_dimension(
            self.snapshot,
            usage,
            llm_calls=llm_calls,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        if dimension is not None:
            raise RunBudgetExhausted(operation, dimension, self.snapshot, usage)

    def record_llm_call(
        self,
        *,
        input_tokens: Optional[int],
        output_tokens: Optional[int],
        cost_usd: Optional[float],
        usage_complete: bool = True,
    ) -> None:
        self.llm_calls += 1
        self.input_tokens += max(0, int(input_tokens or 0))
        self.output_tokens += max(0, int(output_tokens or 0))
        if cost_usd is None or not usage_complete:
            self.unpriced_calls += 1
        if cost_usd is not None:
            self.cost_usd += float(cost_usd)

    def record_tool_call(self, tool_name: str) -> None:
        """一次真实的 Provider 调用。首发和重试都算，它们同样花配额。"""

        self.tool_calls += 1

    def reserve_tool_call(self, operation: str, tool_name: str) -> None:
        """无 await 地检查并记账，保证首发、重试及降级共享调用上限。"""

        self.guard(operation, tool_calls=1)
        self.record_tool_call(tool_name)

    def record_tool_retry(self, tool_name: str) -> None:
        """只计重试；正常首发不能消耗重试额度。"""

        self.tool_retries[tool_name] = self.tool_retries.get(tool_name, 0) + 1

    def tool_retries_exhausted(self, tool_name: str) -> bool:
        """这个工具在这个 Run 上是否已经用完了它的重试轮数。"""

        limit = self.snapshot.max_tool_retries_per_target
        return (
            self.snapshot.enforce_limits
            and limit is not None
            and self.tool_retries.get(tool_name, 0) >= limit
        )

    def report(self) -> Dict[str, Any]:
        """给 SSE / REST / doctor 的那一份读数。"""

        usage = self.usage()
        return {
            "policy_version": self.snapshot.policy_version,
            "enforce_limits": self.snapshot.enforce_limits,
            "limits": self.snapshot.model_dump(mode="json"),
            "usage": usage.model_dump(mode="json"),
            "remaining": remaining_budget(self.snapshot, usage),
        }


_LEDGERS: Dict[str, RunBudgetLedger] = {}


def ledger_for(run_id: str, snapshot: RunBudgetSnapshot) -> RunBudgetLedger:
    """这个 Run 在本进程的账本，首次使用时按快照建立。

    快照换了（编辑行程后重新授权）就换一本账：新的一代 Draft 有自己的预算，旧的消耗
    量属于上一代。
    """

    existing = _LEDGERS.get(run_id)
    if existing is not None and existing.snapshot == snapshot:
        return existing
    ledger = RunBudgetLedger(run_id=run_id, snapshot=snapshot)
    _LEDGERS[run_id] = ledger
    return ledger


def peek_ledger(run_id: Optional[str]) -> Optional[RunBudgetLedger]:
    if not run_id:
        return None
    return _LEDGERS.get(run_id)


def release_ledger(run_id: Optional[str]) -> None:
    if run_id:
        _LEDGERS.pop(run_id, None)


def reset_ledgers() -> None:
    """只供测试在用例之间隔离账本。"""

    _LEDGERS.clear()


async def seed_run_budget(
    run_id: str,
    snapshot: RunBudgetSnapshot,
    *,
    cost_ledger_store: Any,
) -> RunBudgetLedger:
    """把台账里已花的 token/费用读回本进程的账本。

    只做一次（``seeded``）。读不到台账时**不清零**也不阻断：账本从 0 起算意味着一个
    恢复的 Run 可能多花一轮，而拒绝启动意味着它一点都跑不了 —— 前者是可以看见的偏差，
    后者是一次不必要的中断。
    """

    ledger = ledger_for(run_id, snapshot)
    if ledger.seeded:
        return ledger
    ledger.seeded = True
    try:
        summary = await cost_ledger_store.run_summary(run_id)
    except Exception as exc:
        logger.warning("预算基线读取失败，账本从 0 起算 | run=%s error=%s", run_id, exc)
        return ledger
    totals = summary or {}
    ledger.llm_calls = int(totals.get("call_count") or 0)
    ledger.input_tokens = int(totals.get("total_input_tokens") or 0)
    ledger.output_tokens = int(totals.get("total_output_tokens") or 0)
    ledger.cost_usd = float(totals.get("total_cost_usd") or 0.0)
    ledger.unpriced_calls = max(0, int(totals.get("unpriced_call_count") or 0))
    if totals.get("cost_complete") is False:
        ledger.unpriced_calls = max(1, ledger.unpriced_calls)
    if ledger.llm_calls:
        logger.info(
            "预算基线已载入 | run=%s calls=%d in=%d out=%d cost=%.6f",
            run_id,
            ledger.llm_calls,
            ledger.input_tokens,
            ledger.output_tokens,
            ledger.cost_usd,
        )
    return ledger


def current_budget_ledger() -> Optional[RunBudgetLedger]:
    """这个执行上下文的预算账本；没有封存过预算的 Run 返回 ``None``。

    ``None`` 是合法状态而不是错误：快问快答与授权之前的阶段不封预算，那些路径本来就
    受 Deadline 约束，给它们凭空造一份预算等于给一个没有 owner 的数字下判断。
    """

    snapshot = current_run_budget.get()
    run_id = current_run_id.get()
    if snapshot is None or not run_id:
        return peek_ledger(run_id)
    return ledger_for(run_id, snapshot)


async def ensure_budget_baseline() -> Optional[RunBudgetLedger]:
    """让这个 Run 在本进程的账本带上台账里已花的量，只做一次。

    在**第一个节点边界**做而不是在图入口：预算快照只有在 Draft 被授权之后才存在，
    而入口那一刻还不知道这个 Run 有没有预算。
    """

    snapshot = current_run_budget.get()
    run_id = current_run_id.get()
    if snapshot is None or not run_id:
        return None
    ledger = ledger_for(run_id, snapshot)
    if ledger.seeded:
        return ledger
    from ..storage.cost_ledger_store import get_cost_ledger_store

    return await seed_run_budget(
        run_id, snapshot, cost_ledger_store=get_cost_ledger_store()
    )


def guard_run_budget(
    operation: str,
    *,
    llm_calls: int = 0,
    tool_calls: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    """在发起一次新调用之前判预算。超出即抛 `RunBudgetExhausted`。

    参数是**本次最坏开销**的预估。调用之后再记账拦不住超支，所以这一跳必须发生在
    调用之前。
    """

    ledger = current_budget_ledger()
    if ledger is None:
        return
    ledger.guard(
        operation,
        llm_calls=llm_calls,
        tool_calls=tool_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
