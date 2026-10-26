"""费用展示。"""

from __future__ import annotations

from travel_agent.planning.costs.coverage import CostCoverageSummary


def format_cny(value: float) -> str:
    """按各交付界面统一的方式格式化金额。"""

    return f"¥{value:,.0f}"


def cost_coverage_statement(summary: CostCoverageSummary) -> str:
    """只陈述逐项价格；模型给出的无依据总额不算预算。

    complete 覆盖度只表示已列组件，不包含行程的全部杂费；缺失价格的组件由报告
    单独列出。没有任何已定价组件时不给出金额，只提示以实际预订为准。
    """

    if summary.coverage == "none":
        return "具体费用待商家确认，以实际预订为准"
    if summary.coverage == "complete" and summary.estimated_total_cny is not None:
        return f"已列项目预计合计 {format_cny(summary.estimated_total_cny)}"
    if summary.known_subtotal_cny is not None:
        return (
            f"已有价格小计 {format_cny(summary.known_subtotal_cny)}，"
            "不代表整趟总费用，未含部分需向商家核对"
        )
    return "具体费用待商家确认，以实际预订为准"
