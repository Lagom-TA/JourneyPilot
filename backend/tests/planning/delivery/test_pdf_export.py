"""PDF 与阅读版共用同一份安静、完整的正文结构。"""

import os
from datetime import date, datetime, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest
from pypdf import PdfReader
from reportlab.lib.styles import getSampleStyleSheet

from travel_agent.integrations.pdf_readiness import PdfFontUnavailable
from travel_agent.planning.delivery.pdf_export import _timeline_row, render_trip_report_pdf
from travel_agent.planning.references import EntityRef, EntityType


def _bundle():
    document = SimpleNamespace(
        title="测试旅行",
        overview="两天城市漫步。",
        duration_days=2,
        cost_coverage_statement="已列费用约 ¥100",
        highlights=[],
        days=[],
        weather=[],
        selections=[
            SimpleNamespace(
                options=[
                    SimpleNamespace(
                        selected=False,
                        name="不应进入正文的候选",
                        citation_ids=[],
                        selection_reasons=[],
                        tradeoff=None,
                    )
                ]
            )
        ],
        unresolved=[],
    )
    itinerary = SimpleNamespace(
        visit_stops=[],
        dining_stops=[],
        lodging_stays=[],
        transport_legs=[],
    )
    return SimpleNamespace(
        manifest=SimpleNamespace(
            bundle_id="bundle-test",
            workspace_revision=1,
            fact_data_revision=2,
            weather_data_revision=3,
        ),
        workspace=SimpleNamespace(
            itinerary=itinerary,
        ),
        weather_snapshot=SimpleNamespace(
            coverage=[],
            adjustment_proposals=[],
        ),
        report_projection=SimpleNamespace(
            source_workspace_revision=1,
            source_fact_data_revision=2,
            source_weather_data_revision=3,
            status="ready",
            document=document,
            citations=[],
        ),
    )


def test_pdf_contains_trip_content_without_noise_sections():
    bundle = _bundle()
    bundle.report_projection.document.days = [SimpleNamespace(
        day=1, date=date(2026, 10, 26), destination_id="city",
        destination_name="目的地", theme="待安排", blocks=[],
    )]
    bundle.report_projection.document.unresolved = ["缺少可核实的交通安排"]
    try:
        artifact = render_trip_report_pdf(
            bundle,
            exported_at=datetime(2026, 10, 26, tzinfo=timezone.utc),
        )
    except PdfFontUnavailable as exc:
        if os.getenv("JOURNEY_PDF_FONT_REQUIRED") == "1":
            pytest.fail(f"no embeddable CJK font for PDF export: {exc}")
        pytest.skip(f"no embeddable CJK font for PDF export: {exc}")
    reader = PdfReader(BytesIO(artifact.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert "测试旅行" in text
    assert "已列费用约 ¥100" not in text
    assert "当日尚未安排" in text
    assert "缺少可核实的交通安排" in text
    assert "其它合格选择" not in text
    assert "出发前事项" not in text
    assert "数据说明" not in text


def test_pdf_places_each_citation_next_to_the_supported_field():
    block = SimpleNamespace(
        entity_ref=EntityRef(entity_type=EntityType.VISIT_STOP, entity_id="visit"),
        entity_kind="visit", title="博物馆", summary="文化体验",
        citation_ids=["name", "hours"],
        details={"time_label": "10:00", "duration_label": "1 小时", "price_label": "¥80",
                 "facts": ["开放：09:00–17:00"], "notes": [], "segment_lines": []},
    )
    citations = {
        "name": SimpleNamespace(field_paths=["name"]),
        "hours": SimpleNamespace(field_paths=["opening_window"]),
    }
    normal = getSampleStyleSheet()["Normal"]
    styles = {"timeline_time": normal, "timeline_title": normal}
    basis = SimpleNamespace(stated_basis_for=lambda *_: None)

    row = _timeline_row(block, {"name": 1, "hours": 2}, citations, styles, basis)
    text = row._cellvalues[0][1].text

    assert "博物馆</b><super>[1]</super>" in text
    assert "开放：09:00–17:00<super>[2]</super>" in text
    assert "¥80" in text
