"""PDF 与阅读版共用同一份安静、完整的正文结构。"""

import os
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest
from pypdf import PdfReader

from travel_agent.integrations.pdf_readiness import PdfFontUnavailable
from travel_agent.planning.delivery.pdf_export import render_trip_report_pdf


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
    try:
        artifact = render_trip_report_pdf(
            _bundle(),
            exported_at=datetime(2026, 10, 26, tzinfo=timezone.utc),
        )
    except PdfFontUnavailable as exc:
        if os.getenv("JOURNEY_PDF_FONT_REQUIRED") == "1":
            pytest.fail(f"no embeddable CJK font for PDF export: {exc}")
        pytest.skip(f"no embeddable CJK font for PDF export: {exc}")
    reader = PdfReader(BytesIO(artifact.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert "测试旅行" in text
    assert "已列费用约 ¥100" in text
    assert "其它合格选择" not in text
    assert "出发前事项" not in text
    assert "数据说明" not in text
