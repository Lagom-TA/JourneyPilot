"""Research context is a task view; durable evidence remains intact."""

from __future__ import annotations

import json

import pytest

from tests.fixtures.research_packets import (
    make_packet,
    make_research_query,
)
from travel_agent.memory.research_context import (
    format_worker_research_context,
    project_research_context,
)
from travel_agent.planning.outcomes import CandidateResearchGap


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
    assert view["repair_packets"] == []
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
    # View values are copies, so a prompt consumer cannot rewrite durable evidence.
    candidate["name"] = "changed"
    facts["estimated_cost_cny"]["asserted_value"] = 0
    facts["accessibility_metadata"]["asserted_value"]["routes"].append("changed")
    assert packet.model_dump(mode="json") == before


@pytest.mark.parametrize("via_gap", [False, True])
def test_targeted_repair_keeps_selected_entity_complete_evidence_closure(via_gap):
    packet = make_packet(
        entities=(("visit_a", "tokyo"), ("visit_b", "tokyo")), extra_facts=True
    )
    before = packet.model_dump(mode="json")
    gap = CandidateResearchGap(
        gap_id="gap_a",
        worker_kind="destination_researcher",
        reason="missing_comparison_fact",
        candidate_id="visit_a",
        generation_id="generation_test",
        field_path="wheelchair_access",
        destination_id="tokyo",
        query_id="query_test",
    )
    view = project_research_context(
        {"packet": packet},
        **_scope(
            worker_kind="destination_researcher",
            gaps=[gap] if via_gap else [],
            assignment={} if via_gap else {"excluded_candidate_ids": ["visit_a"]},
        ),
    )
    assert not view.coordination
    closure = view.repair_packets[0]
    assert [candidate["candidate_id"] for candidate in closure["candidates"]] == [
        "visit_a"
    ]
    assert {fact["entity_ref"]["entity_id"] for fact in closure["fact_assertions"]} == {
        "visit_a"
    }
    assert {fact["status"] for fact in closure["fact_assertions"]} >= {
        "verified",
        "conflict",
        "missing",
    }
    assert {source["source_record_id"] for source in closure["source_records"]} == {
        "source_visit_a",
        "contradictory_visit_a",
    }
    for source in closure["source_records"]:
        original = next(
            s
            for s in before["source_records"]
            if s["source_record_id"] == source["source_record_id"]
        )
        assert source["snapshot"] == original["snapshot"]
        assert source["content_hash"] == original["content_hash"]
    assert {
        item["candidate_id"] for item in closure["candidate_discovery_records"]
    } == {"visit_a"}
    assert all(
        item["entity_ref"]["entity_id"] == "visit_a"
        for item in closure["field_provenance"]
    )
    assert "query_context" not in closure
    closure["source_records"][0]["snapshot"]["name"] = "changed"
    assert packet.model_dump(mode="json") == before


def test_unassigned_open_gaps_do_not_broaden_scope_but_explicit_target_can():
    packet = make_packet(entities=(("visit_other", "osaka"),))
    gap = CandidateResearchGap(
        gap_id="gap_other",
        worker_kind="destination_researcher",
        reason="missing_comparison_fact",
        candidate_id="visit_other",
        generation_id="generation_test",
        destination_id="osaka",
        query_id="query_other",
        field_path="wheelchair_access",
    )
    packets = {"packet": packet}
    view = project_research_context(
        packets, **_scope(worker_kind="destination_researcher", gaps=[gap])
    )
    assert not view.repair_packets
    explicit = project_research_context(
        packets,
        **_scope(
            worker_kind="destination_researcher",
            assignment={"excluded_candidate_ids": ["visit_other"]},
        ),
    )
    assert explicit.repair_packets[0]["candidates"][0]["destination_id"] == "osaka"


@pytest.mark.parametrize(
    "status,generation,worker",
    [
        ("resolved", "generation_test", "destination_researcher"),
        ("exhausted", "generation_test", "destination_researcher"),
        ("open", "generation_old", "destination_researcher"),
        ("open", "generation_test", "transport_researcher"),
    ],
)
def test_closed_old_or_other_worker_gaps_do_not_trigger_repair(
    status, generation, worker
):
    packet = make_packet()
    gap = CandidateResearchGap(
        gap_id="gap",
        worker_kind=worker,
        reason="missing_comparison_fact",
        candidate_id="visit_a",
        generation_id=generation,
        status=status,
        field_path="wheelchair_access",
    )
    view = project_research_context(
        {"packet": packet}, **_scope(worker_kind="destination_researcher", gaps=[gap])
    )
    assert not view.repair_packets and not view.coordination


@pytest.mark.parametrize("worker", ["accommodation_researcher", "transport_researcher"])
def test_each_worker_receives_own_repair_closure(worker):
    packet = make_packet(worker=worker, extra_facts=True)
    view = project_research_context(
        {"packet": packet},
        **_scope(
            worker_kind=worker,
            assignment={"excluded_candidate_ids": ["visit_a"]},
        ),
    )
    assert not view.coordination
    assert view.repair_packets[0]["candidates"] == [
        packet.candidates[0].model_dump(mode="json", exclude_none=True)
    ]
    assert len(view.repair_packets[0]["source_records"]) == 2


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
