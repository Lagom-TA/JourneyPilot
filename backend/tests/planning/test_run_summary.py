"""追踪摘要与运行时状态只用当前的 workspace 名称，不留版本后缀。"""

from __future__ import annotations

from travel_agent.planning.run_summary import build_trip_run_state_summary
from travel_agent.planning.state import TravelAgentState


def test_run_state_summary_and_state_fields_use_current_workspace_names() -> None:
    summary = build_trip_run_state_summary(TravelAgentState())
    assert summary["has_workspace"] is False
    assert "has_itinerary" not in summary
    assert "has_workspace_v2" not in summary

    fields = set(TravelAgentState.model_fields)
    assert "trip_workspace" in fields
    assert [name for name in fields if name.endswith("_v2")] == []
