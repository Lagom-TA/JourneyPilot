"""工具结果公开投影：旅行者事实、来源、计数和参数安全。"""

from __future__ import annotations

import json

import pytest

from travel_agent.api.sse_projection import project_sse_payload
from travel_agent.conversation.chat.presentation import ChatPresentation
from travel_agent.conversation.chat.tool_events import _handle_tool_done, _handle_tool_start
from travel_agent.memory.chat_session import _project_events_to_messages
from travel_agent.tools.display import _summarize_tool_result, public_args_summary, result_preview
from travel_agent.tools.governance import summarize_tool_result
from travel_agent.tools.result import ToolResultOutcome, classify_tool_result


def test_documents_preview_keeps_excerpt_and_safe_source_only():
    rows = result_preview(
        {
            "documents": [
                {
                    "content": "故宫开放时间与预约方式说明",
                    "source": "/Users/private/data/destinations__beijing.md",
                    "collection": "destinations",
                    "published_at": "2026-01-02",
                    "source_record_id": "secret-record",
                    "chunk_id": "secret-chunk",
                }
            ]
        }
    )
    assert rows == [
        {
            "title": "beijing",
            "detail": "目的地资料 · 2026-01-02 · 故宫开放时间与预约方式说明",
        }
    ]
    serialized = json.dumps(rows, ensure_ascii=False)
    assert "/Users/private" not in serialized
    assert "secret-record" not in serialized
    assert "secret-chunk" not in serialized


def test_documents_preview_links_http_sources_by_hostname():
    rows = result_preview(
        {
            "documents": [
                {
                    "content": "海边步行路线",
                    "source": "https://guides.example.com/coast/walk",
                    "collection": "travel_tips",
                }
            ]
        }
    )
    assert rows[0]["title"] == "guides.example.com"
    assert rows[0]["url"] == "https://guides.example.com/coast/walk"
    assert "guides.example.com/coast" not in rows[0]["title"]


def test_documents_preview_drops_secret_like_excerpts():
    rows = result_preview(
        {
            "documents": [
                {
                    "content": "api_key=sk-secret 故宫预约说明",
                    "source": "factory/destinations__beijing.md",
                    "collection": "destinations",
                }
            ]
        }
    )
    assert "sk-secret" not in json.dumps(rows, ensure_ascii=False)
    assert rows[0]["title"] == "beijing"
    assert "故宫预约说明" not in rows[0].get("detail", "")


def test_place_preview_adds_type_distance_and_short_address_without_identity_fields():
    rows = result_preview(
        {
            "results": [
                {
                    "name": "故宫博物院",
                    "address": "故宫博物院, 景山前街, 东城区, 北京市",
                    "provider_place_type": "tourism;museum",
                    "destination_distance_km": 1.234,
                    "place_id": "osm:relation:1",
                    "latitude": 39.9,
                    "longitude": 116.4,
                }
            ]
        }
    )
    assert rows[0]["title"] == "故宫博物院"
    detail = rows[0]["detail"]
    assert "博物馆" in detail
    assert "距目的地约 1.2 公里" in detail
    assert "景山前街" in detail
    assert "故宫博物院，景山前街" not in detail
    serialized = json.dumps(rows, ensure_ascii=False)
    assert "osm:relation:1" not in serialized
    assert "39.9" not in serialized


def test_place_preview_does_not_invent_distance_for_zero_or_negative():
    # 0 只说明坐标重合，负数不是有效距离；都不能写成“就在目的地附近”。
    for distance in (0, -1):
        rows = result_preview(
            {"results": [{"name": "某地", "destination_distance_km": distance}]}
        )
        assert rows == [{"title": "某地"}]


def test_candidate_named_fields_are_recognized():
    rows = result_preview(
        {
            "results": [
                {"property_name": "某某酒店", "address": "某路 1 号", "provider_place_type": "住宿服务;宾馆"},
                {"branch_name": "某某餐厅", "address": "某路 2 号", "provider_place_type": "餐饮服务;餐厅"},
            ]
        }
    )
    assert [row["title"] for row in rows] == ["某某酒店", "某某餐厅"]
    assert "住宿" in rows[0]["detail"]
    assert "餐厅" in rows[1]["detail"]


def test_knowledge_empty_and_partial_failure_are_distinct():
    assert summarize_tool_result({"documents": [], "failures": []}) == "没有匹配的结果"
    assert summarize_tool_result(
        {"documents": [], "failures": [{"collection": "destinations"}]}
    ) == "部分资料库暂不可用"
    assert summarize_tool_result(
        {"documents": [{"content": "x"}], "failures": [{"collection": "destinations"}]}
    ) == "读到 1 段资料库资料（部分来源暂不可用）"


def test_web_text_content_uses_readable_preview_without_line_count():
    summary = _summarize_tool_result(
        "free_web_search",
        {"success": True, "content": "杭州西湖雨天散步指南\n沿途有树荫与咖啡馆"},
    )
    assert summary == "网页资料：杭州西湖雨天散步指南"
    assert "2 条" not in summary


def test_weather_range_uses_night_as_low_and_day_as_high():
    summary = summarize_tool_result(
        {
            "forecasts": [
                {
                    "city": "北京",
                    "casts": [{"dayweather": "晴", "daytemp": "25", "nighttemp": "12"}],
                }
            ]
        }
    )
    assert summary == "北京 晴 12~25°C"


def test_place_count_uses_the_same_deduplicated_set_as_the_names():
    summary = summarize_tool_result(
        {
            "results": [
                {"place_id": "a", "name": "甲"},
                {"place_id": "b", "name": "乙"},
                {"place_id": "a", "name": "甲"},
            ]
        }
    )
    assert summary == "找到 2 个结果：甲、乙"


@pytest.mark.parametrize(
    "result",
    [
        {"success": True, "documents": [{"content": "x"}]},
        {"success": True, "web": [{"title": "x"}]},
        {"success": True, "forecasts": [{"city": "x"}]},
    ],
)
def test_classify_tool_result_recognizes_documents_web_and_forecasts(result):
    outcome, _ = classify_tool_result("some_tool", result)
    assert outcome is ToolResultOutcome.CONTENT


def test_public_args_summary_redacts_secrets_and_keeps_query():
    summary = public_args_summary(
        '{"query":"西湖","api_key":"sk-secret","passport":"E12345678"}'
    )
    assert "西湖" in summary
    assert "sk-secret" not in summary
    assert "E12345678" not in summary
    assert "api_key=[已隐藏]" in summary
    assert "passport=[已隐藏]" in summary


async def test_tool_events_keep_degraded_in_history_and_drop_fallback_names():
    ctx = ChatPresentation(message_id="m", session_id="s", mode="deep", use_deep_research=True)
    start_info = {
        "name": "global_place_search",
        "tool_call_id": "place-search",
        "args_summary": '{"query":"西湖","api_key":"sk-secret"}',
        "category": "search",
    }
    start_events = [event async for event in _handle_tool_start(("tool_start", "destination_researcher", start_info), ctx)]
    start_event = project_sse_payload(start_events[0])
    assert "sk-secret" not in json.dumps(start_event, ensure_ascii=False)
    assert "西湖" in start_event["args_summary"]

    done_info = {
        "name": "global_place_search",
        "tool_call_id": "place-search",
        "summary": "找到 1 个结果",
        "status": "degraded",
        "degraded": True,
        "category": "search",
        "fallback_from": "secret_provider",
        "fallback_to": "free_web_search",
    }
    done_events = [event async for event in _handle_tool_done(("tool_done", "destination_researcher", done_info), ctx)]
    done_event = project_sse_payload(done_events[0])
    assert "fallback_from" not in done_event
    assert "fallback_to" not in done_event
    assert ctx.thinking_steps[-1]["tool_status"] == "degraded"
    assert "sk-secret" not in json.dumps(ctx.thinking_steps, ensure_ascii=False)


def test_history_projection_sanitizes_old_args_and_preserves_degraded():
    rows = [
        {"event_type": "message.assistant", "payload": {"message_id": "m", "content": "行程已生成"}},
        {
            "event_type": "thinking.step",
            "payload": {
                "message_id": "m",
                "is_tool_call": True,
                "tool_name": "global_place_search",
                "tool_status": "degraded",
                "tool_args": '{"query":"西湖","api_key":"sk-secret"}',
                "content": '{"query":"西湖","api_key":"sk-secret"}',
                "tool_result": "找到 1 个结果",
            },
        },
    ]
    step = _project_events_to_messages(rows)[0]["thinking_steps"][0]
    serialized = json.dumps(step, ensure_ascii=False)
    assert step["tool_status"] == "degraded"
    assert "sk-secret" not in serialized
    assert "西湖" in step["tool_args"]
