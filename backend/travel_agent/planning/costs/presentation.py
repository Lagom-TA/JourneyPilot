"""费用展示。"""

from __future__ import annotations

from travel_agent.planning.costs.coverage import CostCoverageSummary


def format_cny(value: float) -> str:
    """按各交付界面统一的方式格式化金额。"""

    return f"¥{value:,.0f}"


def cost_coverage_statement(summary: CostCoverageSummary) -> str:
    """用约数呈现费用，不混入预订或核查状态。"""

    estimated = (
        summary.estimated_total_cny
        if summary.estimated_total_cny is not None
        else summary.llm_estimated_total_cny
    )
    if estimated is not None:
        return f"全程约 {format_cny(estimated)}"
    if summary.known_subtotal_cny is not None:
        return f"已列费用约 {format_cny(summary.known_subtotal_cny)}"
    return "费用按行程逐项列出"
