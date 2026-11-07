"""公开费用摘要只给出覆盖事实，不给出合并金额。"""

from __future__ import annotations

from travel_agent.planning.costs.coverage import CostCoverageSummary, build_cost_coverage_summary
from travel_agent.planning.delivery.public.itinerary import _public_cost_summary

_COVERAGE_FIELDS = {
    "known_subtotal_cny",
    "estimated_total_cny",
    "priced_component_count",
    "budget_relevant_component_count",
    "coverage",
}


def test_public_cost_summary_publishes_only_coverage_facts() -> None:
    summary = CostCoverageSummary.empty()
    assert set(_public_cost_summary(summary)) == _COVERAGE_FIELDS


def test_public_cost_summary_omits_combined_amounts() -> None:
    public = _public_cost_summary(build_cost_coverage_summary([100, 200]))
    assert public["known_subtotal_cny"] is None
    assert public["estimated_total_cny"] is None
    assert public["priced_component_count"] == 2
