"""Planning costs presentation."""

from __future__ import annotations

from travel_agent.planning.costs.coverage import CostCoverageSummary
from typing import Optional


def format_cny(value: float) -> str:
    """Format an amount the one way every delivery surface prints it."""

    return f"¥{value:,.0f}"


def cost_coverage_statement(summary: CostCoverageSummary) -> Optional[str]:
    """State itemized prices only; a model's unsupported total is not a budget.

    Complete coverage refers to the listed components, not every incidental
    expense of a trip. The report separately names the components missing prices.
    """

    parts: list[str] = []
    if summary.coverage == "complete" and summary.estimated_total_cny is not None:
        parts.append(f"已列项目预计合计 {format_cny(summary.estimated_total_cny)}")
    elif summary.coverage == "partial" and summary.known_subtotal_cny is not None:
        parts.append(
            f"已有价格小计 {format_cny(summary.known_subtotal_cny)}，不代表整趟总费用"
        )
    return " · ".join(parts) or None
