"""来源规范化：未知字段剔除、缺核心字段的条目丢弃并清理悬空链接。"""

from travel_agent.planning.research.output.sources import _drop_dangling_source_links
from travel_agent.planning.research.output.sources import _sanitize_model_source_records


def test_sanitize_drops_tool_call_shaped_sources_and_cleans_links():
    payload = {
        "source_records": [
            {
                "source_record_id": "sr_valid",
                "source_kind": "external_web",
                "title": " valid title ",
                "provider_name": "example",
                "public_excerpt": "excerpt",
                "snapshot": {"name": "兵马俑"},
                "unexpected_field": "drop-me",
            },
            {
                "id": "global_place_search_27_8e754868",
                "name": "global_place_search",
                "arguments": {"query": "兵马俑"},
            },
        ],
        "fact_assertions": [
            {
                "fact_assertion_id": "fact_1",
                "source_links": [
                    {"source_record_id": "sr_valid", "relation": "supports"},
                    {"source_record_id": "global_place_search_27_8e754868", "relation": "supports"},
                ],
            }
        ],
        "candidates": [
            {"candidate_id": "c1", "source_record_ids": ["sr_valid", "global_place_search_27_8e754868"]}
        ],
    }

    _sanitize_model_source_records(payload, default_retrieved_at="2026-10-26T00:00:00Z")

    assert len(payload["source_records"]) == 1
    source = payload["source_records"][0]
    assert source["source_record_id"] == "sr_valid"
    assert "unexpected_field" not in source
    assert source["retrieved_at"] == "2026-10-26T00:00:00Z"
    assert [link["source_record_id"] for link in payload["fact_assertions"][0]["source_links"]] == ["sr_valid"]
    assert payload["candidates"][0]["source_record_ids"] == ["sr_valid"]


def test_dangling_source_links_are_dropped_without_rejecting_the_packet():
    payload = {
        "source_records": [{"source_record_id": "sr_known"}],
        "fact_assertions": [
            {
                "fact_assertion_id": "fact_1",
                "source_links": [
                    {"source_record_id": "sr_known", "relation": "supports"},
                    {"source_record_id": "sr_unknown", "relation": "supports"},
                ],
            }
        ],
        "candidates": [{"candidate_id": "c1", "source_record_ids": ["sr_known", "sr_unknown"]}],
    }

    _drop_dangling_source_links(payload)

    assert [link["source_record_id"] for link in payload["fact_assertions"][0]["source_links"]] == ["sr_known"]
    assert payload["candidates"][0]["source_record_ids"] == ["sr_known"]
