"""研究上下文是任务视图，持久证据保持不变。"""

from __future__ import annotations

import json

from tests.fixtures.research_packets import (
    make_packet,
    make_research_query,
)
from travel_agent.memory.research_context import (
    format_worker_research_context,
    project_research_context,
)


def _scope(**overrides):
    return {
        "worker_kind": "accommodation_researcher",
        "run_id": "run_test",
        "generation_id": "generation_test",
        "planned_queries": [make_research_query()],
        "assignment": {},
        **overrides,
    }


def test_view_filters_runs_generations_destinations_and_keeps_latest_candidate():
    old = make_packet("old", revision=1)
    new = make_packet("new", revision=2)
    other_city = make_packet("other_city", entities=(("visit_other", "osaka"),))
    other_run = make_packet(
        "other_run", entities=(("visit_run", "tokyo"),), run_id="run_other"
    )
    other_generation = make_packet(
        "other_gen", entities=(("visit_gen", "tokyo"),), generation="generation_old"
    )
    packets = {
        p.research_packet_id: p
        for p in (old, new, other_city, other_run, other_generation)
    }
    scope = _scope(planned_queries=[make_research_query(), make_research_query("osaka", "generation_old")])
    first = format_worker_research_context(packets, **scope)
    second = format_worker_research_context(
        dict(reversed(list(packets.items()))), **scope
    )
    assert first == second
    view = json.loads(first)
    assert view["destination_ids"] == ["tokyo"]
    assert [item["research_packet_id"] for item in view["coordination"]] == ["new"]
    assert view["coordination"][0]["candidates"][0]["candidate_id"] == "visit_a"
    assert (
        project_research_context(
            packets, **_scope(worker_kind="destination_researcher")
        ).coordination
        == []
    )


def test_coordination_preserves_values_units_validity_and_source_links_without_snapshots():
    packet = make_packet(extra_facts=True)
    before = packet.model_dump(mode="json")
    view = project_research_context({"packet": packet}, **_scope())
    coordination = view.coordination[0]
    candidate = coordination.candidates[0]
    assert candidate["name"] == packet.candidates[0].name
    assert candidate["address"] == packet.candidates[0].address
    assert "fact_assertion_ids" not in candidate
    facts = {fact["field_path"]: fact for fact in coordination.facts}
    price = facts["estimated_cost_cny"]
    assert (price["asserted_value"], price["unit"], price["currency"]) == (
        80,
        "per_visit",
        "CNY",
    )
    assert price["effective_from"] and price["effective_to"] and price["expires_at"]
    assert facts["wheelchair_access"]["status"] == "missing"
    assert {link["relation"] for link in facts["opening_window"]["source_links"]} == {
        "supports",
        "contradicts",
    }
    sources = {
        source["source_record_id"]: source for source in coordination.source_references
    }
    assert set(sources) == {"source_visit_a", "contradictory_visit_a"}
    assert (
        sources["source_visit_a"]["content_hash"]
        == packet.source_records[0].content_hash
    )
    assert (
        sources["source_visit_a"]["retrieved_at"]
        and sources["source_visit_a"]["provider_valid_until"]
    )
    for source in sources.values():
        assert "snapshot" not in source and "public_excerpt" not in source
    assert packet.model_dump(mode="json") == before
    # 视图值是副本，读取 prompt 的代码无法改写持久证据。
    candidate["name"] = "changed"
    facts["estimated_cost_cny"]["asserted_value"] = 0
    facts["accessibility_metadata"]["asserted_value"]["routes"].append("changed")
    assert packet.model_dump(mode="json") == before


def test_transport_coordination_preserves_endpoints_segments_and_timing():
    packet = make_packet(worker="transport_researcher")
    view = project_research_context({"packet": packet}, **_scope())
    candidate = view.coordination[0].candidates[0]
    assert candidate["from_endpoint"] == candidate["segments"][0]["from_endpoint"]
    assert candidate["to_endpoint"] == candidate["segments"][-1]["to_endpoint"]
    assert [segment["mode"] for segment in candidate["segments"]] == ["metro", "bus"]
    assert (
        candidate["segments"][0]["departure_at"]
        and candidate["segments"][1]["arrival_at"]
    )
    assert (
        candidate["segments"]
        == packet.candidates[0].model_dump(mode="json")["segments"]
    )
