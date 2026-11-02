"""报告合同不再携带 important_notes：它没有任何渲染方。"""

from __future__ import annotations

from travel_agent.planning.delivery.projections import TripReportDocument
from travel_agent.planning.itinerary.models import StructuredItinerary


def test_report_contracts_do_not_carry_important_notes() -> None:
    assert "important_notes" not in StructuredItinerary.model_fields
    assert "important_notes" not in TripReportDocument.model_fields
