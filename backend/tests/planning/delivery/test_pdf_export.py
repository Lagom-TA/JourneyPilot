"""PDF 与阅读版共用同一份安静、完整的正文结构。"""

import os
from datetime import date, datetime, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest
from pypdf import PdfReader
from reportlab.lib.styles import getSampleStyleSheet

from travel_agent.integrations.pdf_readiness import PdfFontUnavailable
from travel_agent.planning.delivery.pdf_export import (
    _build_pdf_sources,
    _timeline_row,
    render_trip_report_pdf,
)
from travel_agent.planning.delivery.source_presentation import (
    clean_public_source_excerpt,
    clean_public_source_title,
    public_fact_field_label,
)
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


def test_pdf_groups_identical_sources_and_cleans_provider_machine_prefixes():
    source_a = SimpleNamespace(
        source_record_id="sr_train_1",
        source_kind="external_tool",
        provider_name="12306",
        observed_at=None,
        content_hash="hash",
        title="12306 余票查询：乐山→重庆北（2026-11-18 参考日，无结果）",
        public_excerpt="bookable_train_count=0，参考日无乐山直达重庆北的可售车次。",
        canonical_url=None,
        retrieved_at=datetime(2026, 11, 4, 3, 55, 50, tzinfo=timezone.utc),
        rag_chunk_content=None,
    )
    source_b = SimpleNamespace(
        source_record_id="sr_train_1",
        source_kind="external_tool",
        provider_name="12306",
        observed_at=None,
        content_hash="hash",
        title="12306 余票查询：乐山→重庆北（2026-11-18 参考日，无结果）",
        public_excerpt="bookable_train_count=0，参考日无乐山直达重庆北的可售车次。",
        canonical_url=None,
        retrieved_at=datetime(2026, 11, 4, 3, 55, 50, tzinfo=timezone.utc),
        rag_chunk_content=None,
    )
    citations = [
        SimpleNamespace(
            citation_id="c1",
            entity_ref=EntityRef(entity_type=EntityType.TRANSPORT_LEG, entity_id="leg_1"),
            field_paths=["from_endpoint"],
            sources=[source_a],
        ),
        SimpleNamespace(
            citation_id="c2",
            entity_ref=EntityRef(entity_type=EntityType.TRANSPORT_LEG, entity_id="leg_1"),
            field_paths=["to_endpoint"],
            sources=[source_b],
        ),
    ]
    numbers, entries = _build_pdf_sources(citations)

    assert numbers == {"c1": 1, "c2": 1}
    assert len(entries) == 1
    assert entries[0]["number"] == 1
    assert entries[0]["excerpt"] == "参考日无乐山直达重庆北的可售车次。"
    assert clean_public_source_title("get-tickets 查询结果") == "车次查询结果"
    assert clean_public_source_excerpt("成都市 2026-12-05–2026-12-09 weather forecast") == "成都市 2026-12-05–2026-12-09 天气预报"
    assert public_fact_field_label("opening_window") == "开放时间"


def test_pdf_keeps_distinct_sources_and_snapshots_with_identical_display_text():
    base = dict(
        source_record_id="route_1",
        source_kind="external_tool",
        provider_name="路线查询",
        title="路线查询结果",
        public_excerpt="路线查询结果",
        canonical_url=None,
        retrieved_at=datetime(2026, 11, 4, 3, 55, tzinfo=timezone.utc),
        observed_at=None,
        content_hash="hash",
        rag_chunk_content=None,
    )
    sources = [
        SimpleNamespace(**base),
        SimpleNamespace(**{**base, "source_record_id": "route_2"}),
        SimpleNamespace(**{**base, "retrieved_at": datetime(2026, 11, 5, 3, 55, tzinfo=timezone.utc)}),
    ]
    citations = [
        SimpleNamespace(
            citation_id="c1",
            entity_ref=EntityRef(entity_type=EntityType.TRANSPORT_LEG, entity_id="leg_1"),
            sources=sources,
        ),
        SimpleNamespace(
            citation_id="c2",
            entity_ref=EntityRef(entity_type=EntityType.WEATHER_DAY, entity_id="day_1"),
            sources=[sources[1]],
        ),
    ]

    numbers, entries = _build_pdf_sources(citations)

    assert numbers == {"c1": [1, 2, 3], "c2": 2}
    assert [entry["source"].retrieved_at for entry in entries] == [
        source.retrieved_at for source in sources
    ]


def test_rendered_pdf_includes_distinct_sources_and_retrieval_times():
    bundle = _bundle()
    times = [
        datetime(2026, 11, 4, 3, 55, tzinfo=timezone.utc),
        datetime(2026, 11, 5, 3, 55, tzinfo=timezone.utc),
    ]
    sources = [
        SimpleNamespace(
            source_record_id=f"route_{index}", source_kind="external_tool",
            provider_name="路线查询", title="路线查询结果", public_excerpt="路线查询结果",
            canonical_url=None, retrieved_at=timestamp, observed_at=None,
            content_hash="hash", rag_chunk_content=None,
        )
        for index, timestamp in enumerate(times, 1)
    ]
    bundle.report_projection.citations = [SimpleNamespace(
        citation_id="c1",
        entity_ref=EntityRef(entity_type=EntityType.TRANSPORT_LEG, entity_id="leg_1"),
        sources=sources,
    )]
    try:
        artifact = render_trip_report_pdf(bundle, exported_at=times[0])
    except PdfFontUnavailable as exc:
        if os.getenv("JOURNEY_PDF_FONT_REQUIRED") == "1":
            pytest.fail(f"no embeddable CJK font for PDF export: {exc}")
        pytest.skip(f"no embeddable CJK font for PDF export: {exc}")

    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(artifact.content)).pages)
    assert "[1] 交通安排" in text
    assert "[2] 交通安排" in text
    for timestamp in times:
        assert timestamp.astimezone().strftime("%Y-%m-%d %H:%M") in text
