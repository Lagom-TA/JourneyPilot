"""The single sentence that says how much of the trip the money figure covers.

The same judgement was written three times — the workspace overview, the formal
report header, and the exported PDF — and the three had already drifted: the
workspace omitted the "still N items unpriced" clause the other two printed, so a
traveller comparing the card with the PDF saw the same trip described as more
certain in one place than the other.

The statement is produced once, during projection, and stored on
``TripReportDocument.cost_coverage_statement``.  Every surface prints that field.
Amount formatting lives here too: the PDF used ``¥{value:g}`` while the browser
used ``Intl.NumberFormat``, so the same number appeared as ``¥5600`` and
``¥5,600`` on two renderings of one plan.
"""

from __future__ import annotations

from typing import Optional

from travel_agent.planning.costs.coverage import CostCoverageSummary


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
        parts.append(f"已有价格小计 {format_cny(summary.known_subtotal_cny)}，不代表整趟总费用")
    return " · ".join(parts) or None
