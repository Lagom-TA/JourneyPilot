"""一次 Run 的调用 / token / 费用预算，以及它的消耗读数。

预算和 Deadline 是同一类东西：Run 被授权时封存一份快照，之后改配置既不能让一个在跑
的 Run 多花，也不能让它少花。区别只在计量的单位 —— 时间归 ``RunDeadlineSnapshot``，
**这里不再写一个 max_wall_seconds**：同一件事有两个 owner 时，两个都会被相信一半。

预算耗尽是一个**有名字的原因**（``BudgetDimension``），不是一次「模型失败」。它决定
产品做什么：确定性收口、部分交付、或者带原因的失败 —— 三条路都需要知道是哪一维用完了。
"""

from __future__ import annotations

from typing import Dict, Literal, Optional, get_args

from pydantic import Field

from .contract_base import StrictModel

RUN_BUDGET_POLICY_VERSION = "run_budget.v1"

#: 预算的每一维。名字进 reason code、进 SSE、进日志，所以它是合同的一部分。
BudgetDimension = Literal[
    "llm_calls",
    "tool_calls",
    "input_tokens",
    "output_tokens",
    "cost_usd",
]

#: 同一份清单派生自上面的 Literal，不再手抄一遍。顺序有语义 —— `exhausted_dimension`
#: 按这个顺序判哪一维先耗尽，而 `get_args` 保留 Literal 的书写顺序。
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
            if snapshot.enforce_limits and snapshot.limit(dimension) is not None else None
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
