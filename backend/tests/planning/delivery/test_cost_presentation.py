"""费用文案只提供清晰约数，不混入预订或核查状态。"""

from travel_agent.planning.costs.coverage import build_cost_coverage_summary
from travel_agent.planning.costs.presentation import cost_coverage_statement


def test_complete_cost_is_presented_as_trip_estimate():
    summary = build_cost_coverage_summary([100, 200])
    assert cost_coverage_statement(summary) == "全程约 ¥300"


def test_partial_cost_is_not_presented_as_trip_total():
    summary = build_cost_coverage_summary([100, None])
    assert cost_coverage_statement(summary) == "已列费用约 ¥100"


def test_empty_cost_has_no_booking_or_confirmation_copy():
    summary = build_cost_coverage_summary([])
    assert cost_coverage_statement(summary) == "费用按行程逐项列出"
    assert "确认" not in cost_coverage_statement(summary)
    assert "预订" not in cost_coverage_statement(summary)
