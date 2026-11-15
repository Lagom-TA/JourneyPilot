"""公开交付只清理重复日期假设，不改写事实和原始结果。"""

import os
from datetime import date, datetime, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest
from pypdf import PdfReader
from reportlab.lib.styles import getSampleStyleSheet

from tests.planning.delivery.test_pdf_export import _bundle as pdf_bundle
from tests.planning.delivery.test_public_fact_values import _delivery, _packet
from travel_agent.integrations.pdf_readiness import PdfFontUnavailable
from travel_agent.planning.delivery.fact_projection import build_fact_snapshot
from travel_agent.planning.delivery.pdf_export import _timeline_row, render_trip_report_pdf
from travel_agent.planning.delivery.public.bundle import public_delivery_bundle
from travel_agent.planning.delivery.report_projection import project_report
from travel_agent.planning.delivery.travel_content import (
    clean_date_assumption_text,
    public_lodging_text,
    public_trip_title,
    public_trip_unresolved,
)
from travel_agent.planning.itinerary.title_writing import _SYSTEM_PROMPT
from travel_agent.planning.references import EntityRef, EntityType
from travel_agent.planning.research.accommodation.prompts import TASK_TEMPLATE


NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("东京慢游（参考日期）", "东京慢游"),
        ("东京慢游（参考日期：2026-10-10）", "东京慢游（2026-10-10）"),
        ("东京慢游 — 参考日期：2026-10-10", "东京慢游 — 2026-10-10"),
        ("参考日期", "旅行计划"),
        ("入住日期为规划假设", "旅行计划"),
        ("2026-10-10 京都夜行", "2026-10-10 京都夜行"),
        ("日期变更后的京都旅行", "日期变更后的京都旅行"),
    ],
)
def test_public_trip_title_preserves_meaningful_title_and_actual_dates(value, expected):
    assert public_trip_title(value) == expected
    assert public_trip_title(expected) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("位置便利，入住日期为规划假设，房态需确认。", "位置便利，房态需确认。"),
        ("入住日期为规划假设，但房态需确认。", "房态需确认。"),
        ("入住日期为规划假设。", ""),
        ("位置便利。入住日期为规划假设；2026-10-10 房态待确认。", "位置便利。2026-10-10 房态待确认。"),
        ("2026-10-10入住，退房日期暂定，价格为参考估价", "2026-10-10入住，价格为参考估价"),
        ("入住日期尚未确定，请预订前确认房态", "入住日期尚未确定，请预订前确认房态"),
        ("2026-10-10 入住，价格和房态仍待确认。", "2026-10-10 入住，价格和房态仍待确认。"),
        ("酒店可按入住日期为规划假设调整价格", "酒店可按入住日期为规划假设调整价格"),
        ("入住日期为规划假设时房价不变。", "入住日期为规划假设时房价不变。"),
        ("同时提供接送，入住日期为规划假设。", "同时提供接送。"),
        ("入住日期为规划假设且房态未确认。", "房态未确认。"),
    ],
)
def test_lodging_date_cleanup_is_bounded_and_idempotent(value, expected):
    assert clean_date_assumption_text(value) == expected
    assert clean_date_assumption_text(expected) == expected


def test_lodging_only_assumption_does_not_use_a_fallback():
    assert public_lodging_text("入住日期为规划假设。", fallback="请在预订前核对日期") == ""
    assert public_lodging_text("入住日期为规划假设，地铁便利。") == "地铁便利。"


def test_unresolved_filter_hides_only_redundancy_and_keeps_specific_gaps():
    original = [
        "（入住日期为规划假设）。",
        "出行前核对开放时间和票价。",
        "出发日期暂定。",
        "2026-12-10 餐饮至住宿的接驳尚未核实。",
        "第 6 天尚未安排具体活动。",
        "酒店无法确认入住日期，需另选住宿。",
        "入住日期为规划假设，但2026-12-10房态尚未确认。",
        "入住日期为规划假设，建议预订前确认房态。",
        "出行前核对开放时间和票价，酒店房态未确认。",
    ]
    assert public_trip_unresolved(original) == [
        "2026-12-10 餐饮至住宿的接驳尚未核实。",
        "第 6 天尚未安排具体活动。",
        "酒店无法确认入住日期，需另选住宿。",
        "2026-12-10房态尚未确认。",
        "建议预订前确认房态。",
        "出行前核对开放时间和票价，酒店房态未确认。",
    ]
    assert original[0] == "（入住日期为规划假设）。"


def test_lodging_only_uses_existing_fallback_for_other_unreadable_reasons():
    from travel_agent.planning.delivery.travel_content import selection_reason

    bundle = _legacy_bundle()
    stay = bundle.workspace.itinerary.lodging_stays[0]
    internal = stay.model_copy(update={"selection_reason": "candidate_id 是内部编号"})
    assert selection_reason(internal) == (
        f"计划在 {stay.name} 连住 {stay.nights} 晚；地址：{stay.address}。"
    )
    only_assumption = stay.model_copy(update={
        "selection_reason": "candidate_id 是内部编号；入住日期为规划假设。"
    })
    assert selection_reason(only_assumption) == ""


def test_writer_and_research_prompts_do_not_request_redundant_copy():
    assert "不要写“参考日期”" in _SYSTEM_PROMPT
    assert "选项理由与取舍不要重复写“入住日期为规划假设”" in TASK_TEMPLATE
    assert "保留影响决策的价格、房态与预订不确定性" in TASK_TEMPLATE


def _legacy_bundle():
    visit = _packet("visit", "candidate_visit", {}, [])
    lodging = _packet("lodging", "candidate_lodging", {}, [])
    bundle, _ = _delivery(visit, lodging, lodging_ids=["candidate_lodging"])
    workspace = bundle.workspace
    stay = workspace.itinerary.lodging_stays[0].model_copy(update={
        "selection_reason": "位置便利，入住日期为规划假设，房态需确认。",
    })
    itinerary = workspace.itinerary.model_copy(update={
        "title": "东京漫步（参考日期：2026-10-10）",
        "lodging_stays": [stay],
        "unresolved": ["入住日期为规划假设。", "酒店房态未确认。"],
    })
    slots = []
    for slot in workspace.selection_slots:
        if slot.slot_type == "lodging":
            options = [option.model_copy(update={
                "selection_reasons": ["入住日期为规划假设。", "地铁便利；入住日期为规划假设；房态待确认。"],
                "tradeoff": "入住日期为规划假设，但价格待确认。",
            }) for option in slot.options]
            slot = slot.model_copy(update={"options": options})
        slots.append(slot)
    workspace = workspace.model_copy(update={"itinerary": itinerary, "selection_slots": slots})

    document = bundle.report_projection.document
    assert document is not None
    days = []
    for day in document.days:
        blocks = []
        for block in day.blocks:
            if block.entity_kind == "lodging":
                block = block.model_copy(update={
                    "summary": "入住日期为规划假设，房态未确认。",
                    "details": {
                        **block.details,
                        "node_summary": "车站附近，入住日期为规划假设，房价待确认。",
                        "notes": ["入住日期为规划假设。", "房型尚需确认。"],
                    },
                })
            blocks.append(block)
        days.append(day.model_copy(update={"blocks": blocks}))
    selections = []
    for section in document.selections:
        if section.slot_type == "lodging":
            options = [option.model_copy(update={
                "selection_reasons": ["入住日期为规划假设。", "地铁便利，入住日期为规划假设。"],
                "tradeoff": "入住日期为规划假设，但房态待确认。",
            }) for option in section.options]
            section = section.model_copy(update={"options": options})
        selections.append(section)
    document = document.model_copy(update={
        "title": "东京漫步（参考日期：2026-10-10）",
        "days": days,
        "selections": selections,
        "unresolved": ["出行前核对开放时间和票价。", "酒店房态未确认。"],
    })
    report = bundle.report_projection.model_copy(update={"document": document})
    return bundle.model_copy(update={"workspace": workspace, "report_projection": report})


def test_historical_public_bundle_cleans_only_display_copy_without_mutation():
    bundle = _legacy_bundle()
    before = bundle.model_dump(mode="json")
    public = public_delivery_bundle(bundle)
    itinerary = public["workspace"]["itinerary"]
    document = public["report_projection"]["document"]
    assert itinerary["title"] == document["title"] == "东京漫步（2026-10-10）"
    assert itinerary["unresolved"] == document["unresolved"] == ["酒店房态未确认。"]
    stay = itinerary["lodging_stays"][0]
    assert stay["selection_reason"] == "位置便利，房态需确认。"
    assert (stay["check_in_date"], stay["check_out_date"], stay["availability_status"]) == (
        "2026-10-10", "2026-10-11", "needs_confirmation"
    )
    slot = next(slot for slot in public["workspace"]["selection_slots"] if slot["slot_type"] == "lodging")
    assert slot["options"][0]["selection_reasons"] == ["地铁便利；房态待确认。"]
    assert slot["options"][0]["tradeoff"] == "价格待确认。"
    section = next(section for section in document["selections"] if section["slot_type"] == "lodging")
    assert section["options"][0]["selection_reasons"] == ["地铁便利。"]
    assert section["options"][0]["tradeoff"] == "房态待确认。"
    assert section["options"][0]["availability_status"] == "needs_confirmation"
    block = next(block for day in document["days"] for block in day["blocks"] if block["entity_kind"] == "lodging")
    assert block["summary"] == "房态未确认。"
    assert block["details"]["node_summary"] == "车站附近，房价待确认。"
    assert block["details"]["notes"] == ["房型尚需确认。"]
    assert block["details"]["check_in_date"] == "2026-10-10"
    assert bundle.model_dump(mode="json") == before


def test_new_report_with_assumption_only_does_not_fabricate_option_reason():
    bundle = _legacy_bundle()
    workspace = bundle.workspace
    itinerary = workspace.itinerary
    stay = itinerary.lodging_stays[0].model_copy(update={"selection_reason": "入住日期为规划假设。"})
    itinerary = itinerary.model_copy(update={"lodging_stays": [stay]})
    slots = []
    for slot in workspace.selection_slots:
        if slot.slot_type == "lodging":
            options = [option.model_copy(update={
                "selection_reasons": ["入住日期为规划假设。"],
                "tradeoff": "入住日期为规划假设。",
            }) for option in slot.options]
            slot = slot.model_copy(update={"options": options})
        slots.append(slot)
    workspace = workspace.model_copy(update={"itinerary": itinerary, "selection_slots": slots})
    report = project_report(workspace, build_fact_snapshot(workspace), bundle.weather_snapshot, generated_at=NOW)
    section = next(section for section in report.document.selections if section.slot_type == "lodging")
    assert section.options[0].selection_reasons == ["入住日期为规划假设。"]
    public_bundle = bundle.model_copy(update={"workspace": workspace, "report_projection": report})
    public = public_delivery_bundle(public_bundle)
    assert public["workspace"]["itinerary"]["lodging_stays"][0]["selection_reason"] == ""
    public_section = next(section for section in public["report_projection"]["document"]["selections"] if section["slot_type"] == "lodging")
    assert public_section["options"][0]["selection_reasons"] == []
    assert public_section["options"][0]["tradeoff"] is None


def test_pdf_historical_lodging_row_cleans_notes_but_keeps_dates_and_status():
    block = SimpleNamespace(
        entity_ref=EntityRef(entity_type=EntityType.LODGING_STAY, entity_id="stay"),
        entity_kind="lodging", title="酒店", summary="入住日期为规划假设。",
        citation_ids=[], details={
            "time_label": "15:00", "node_summary": "靠近车站，入住日期为规划假设，房态待确认。",
            "facts": ["入住：2026-10-10", "退房：2026-10-11"],
            "notes": ["入住日期为规划假设。", "房型需确认。"], "segment_lines": [],
        },
    )
    normal = getSampleStyleSheet()["Normal"]
    row = _timeline_row(block, {}, {}, {"timeline_time": normal, "timeline_title": normal},
                        SimpleNamespace(stated_basis_for=lambda *_: None))
    text = row._cellvalues[0][1].text
    assert "入住日期为规划假设" not in text
    assert all(value in text for value in ("靠近车站", "房态待确认", "房型需确认", "2026-10-10", "2026-10-11"))
    assert block.details["notes"][0] == "入住日期为规划假设。"


def test_pdf_historical_title_and_lodging_copy_are_clean_in_text_and_metadata():
    bundle = pdf_bundle()
    document = bundle.report_projection.document
    document.title = "东京慢游（参考日期：2026-10-10）"
    bundle.workspace.itinerary.lodging_stays = [SimpleNamespace(
        stay_id="stay", lineage=SimpleNamespace(lineage_kind="candidate_entity"),
    )]
    block = SimpleNamespace(
        entity_ref=EntityRef(entity_type=EntityType.LODGING_STAY, entity_id="stay"),
        entity_kind="lodging", title="酒店", summary="入住日期为规划假设。",
        citation_ids=[], details={
            "time_label": "15:00", "node_summary": "靠近车站，入住日期为规划假设，房态待确认。",
            "facts": ["入住：2026-10-10"], "notes": ["房型需确认。"], "segment_lines": [],
        },
    )
    document.days = [SimpleNamespace(day=1, date=date(2026, 10, 10), destination_id="city",
                                     destination_name="东京", theme="散步", blocks=[block])]
    try:
        artifact = render_trip_report_pdf(bundle, exported_at=NOW)
    except PdfFontUnavailable as exc:
        if os.getenv("JOURNEY_PDF_FONT_REQUIRED") == "1":
            pytest.fail(f"no embeddable CJK font for PDF export: {exc}")
        pytest.skip(f"no embeddable CJK font for PDF export: {exc}")
    reader = PdfReader(BytesIO(artifact.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "参考日期" not in text and "入住日期为规划假设" not in text
    assert all(value in text for value in ("东京慢游", "2026-10-10", "靠近车站", "房态待确认"))
    assert reader.metadata.title == "东京慢游（2026-10-10）"
    assert document.title == "东京慢游（参考日期：2026-10-10）"
