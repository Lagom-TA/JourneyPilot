"""费用合同只保留真正产物里存在的节点与字段。"""

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


def test_cost_summary_has_no_budget_or_model_estimate_fields() -> None:
    assert set(CostCoverageSummary.model_fields) == _COVERAGE_FIELDS


def test_public_cost_summary_publishes_only_coverage_facts() -> None:
    summary = CostCoverageSummary.empty()
    assert set(_public_cost_summary(summary)) == _COVERAGE_FIELDS


def test_public_cost_summary_omits_combined_amounts() -> None:
    public = _public_cost_summary(build_cost_coverage_summary([100, 200]))
    assert public["known_subtotal_cny"] is None
    assert public["estimated_total_cny"] is None
    assert public["priced_component_count"] == 2


def test_the_planning_graph_has_no_budget_estimate_node() -> None:
    from travel_agent.planning.graph import build_travel_workflow

    assert "budget_estimate" not in build_travel_workflow().nodes
