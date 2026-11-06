"""来源规范化：未知字段剔除、缺核心字段的条目丢弃并清理悬空链接。"""

from travel_agent.planning.research.output.sources import _drop_dangling_source_links
from travel_agent.planning.research.output.sources import _drop_unsourced_facts
from travel_agent.planning.research.output.sources import _sanitize_model_source_records
from travel_agent.planning.research.output.transcript import _retrieved_source_snapshots


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


def test_only_evidence_allowed_search_results_ground_web_sources():
    def message(url, *, allowed, quarantined=False):
        return {"role": "tool", "content": {
            "status": "success", "sanitized_result": {"url": url},
            "metadata": {"evidence_allowed": allowed, "quarantine_result": quarantined},
        }}

    sources = _retrieved_source_snapshots([
        message("https://example.com/valid", allowed=True),
        message("https://example.com/blocked", allowed=False),
        message("https://example.com/quarantined", allowed=True, quarantined=True),
    ])

    assert set(sources) == {"https://example.com/valid"}


def _fact(fact_id, *, status="verified", value="2026-11-09", links=()):
    return {
        "fact_assertion_id": fact_id,
        "status": status,
        "asserted_value": value,
        "source_links": [{"source_record_id": source, "relation": relation} for source, relation in links],
    }


def test_unsourced_facts_are_dropped_instead_of_failing_the_delivery():
    payload = {
        "fact_assertions": [
            _fact("fact_check_in"),
            _fact("fact_sourced", links=[("sr_1", "supports")]),
            _fact("fact_qualified", links=[("sr_1", "qualifies")]),
            _fact("fact_only_contradicting", links=[("sr_1", "contradicts")]),
            _fact("fact_unknown", status="missing", value=None),
        ],
        "candidates": [{
            "candidate_id": "c1",
            "constraint_evaluations": [
                {"status": "passed", "fact_assertion_ids": ["fact_check_in"]},
                {"status": "passed", "fact_assertion_ids": ["fact_check_in", "fact_sourced"]},
            ],
        }],
        "field_provenance": [
            {"origin": "user_input", "reference_ids": ["fact_check_in"]},
            {"origin": "external_fact", "reference_ids": ["fact_sourced", "fact_check_in"]},
        ],
    }

    _drop_unsourced_facts(payload)

    assert [fact["fact_assertion_id"] for fact in payload["fact_assertions"]] == [
        "fact_sourced", "fact_qualified", "fact_unknown",
    ]
    first, second = payload["candidates"][0]["constraint_evaluations"]
    assert first == {"status": "unknown", "fact_assertion_ids": [], "reason_code": "missing_evidence"}
    assert second == {"status": "passed", "fact_assertion_ids": ["fact_sourced"]}
    assert payload["field_provenance"] == [{"origin": "external_fact", "reference_ids": ["fact_sourced"]}]


def test_a_missing_fact_that_still_carries_a_value_is_treated_as_unsupported():
    payload = {"fact_assertions": [_fact("fact_odd", status="missing", value="x")]}

    _drop_unsourced_facts(payload)

    assert payload["fact_assertions"] == []


def test_every_fact_with_support_is_left_untouched():
    payload = {"fact_assertions": [_fact("fact_1", links=[("sr_1", "supports")])], "candidates": []}
    before = [dict(item) for item in payload["fact_assertions"]]

    _drop_unsourced_facts(payload)

    assert payload["fact_assertions"] == before

