"""费用展示。"""

from __future__ import annotations

from travel_agent.planning.costs.coverage import CostCoverageSummary


def format_cny(value: float) -> str:
    """按各交付界面统一的方式格式化金额。"""

    return f"¥{value:,.0f}"


def cost_coverage_statement(summary: CostCoverageSummary) -> str | None:
    """不把已知费用小计表述为完整旅行总额。"""

    return None
