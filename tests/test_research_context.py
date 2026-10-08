"""Research context is a task view; durable evidence remains intact."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from travel_agent.entities.candidate_discovery import CandidateDiscoveryRecord
from travel_agent.entities.delivery_bundle import (
    CandidateResearchGap,
    EntityRef,
    EntityType,
    FactAssertion,
    FactSourceLink,
    FieldProvenance,
    LodgingCandidate,
    ResearchPacket,
    SourceRecord,
    TransportCandidate,
    VisitCandidate,
    WeatherSensitivity,
)
from travel_agent.entities.intent_spec import canonical_json_hash
from travel_agent.entities.research_query_plan import ResearchQuery
from travel_agent.memory.research_context import (
    format_worker_research_context,
    project_research_context,
)

_NOW = datetime(2026, 10, 5, 10, tzinfo=timezone.utc)


def _query(destination="tokyo", generation="generation_test", query_id="query_test"):
    return ResearchQuery(
        query_id=query_id,
        generation_id=generation,
        domain="lodging",
        destination_id=destination,
        query_kind="structural",
        query_text="research places",
        desired_candidate_count=3,
        provider_route="mixed",
        priority=1,
    )


def make_packet(
    packet_id="packet_test",
    *,
    entities=(("visit_a", "tokyo"),),
    run_id="run_test",
    generation="generation_test",
    revision=1,
    extra_facts=False,
    worker="destination_researcher",
):
    """Validated fixture with identity facts and an optional contradictory source."""
    candidates, facts, sources, provenance, discovery = [], [], [], [], []
    for candidate_id, destination in entities:
        identity = {
            "name": f"Museum {candidate_id}",
            "address": f"{destination} Museum Street",
            "place_id": f"place_{candidate_id}",
            "provider_place_type": "tourism;attraction",
            "provider_country_code": "JP",
        }
        entity_type = EntityType.VISIT_STOP
        if worker == "accommodation_researcher":
            identity["property_name"] = identity.pop("name")
            identity["provider_place_type"] = "hotel"
            entity_type = EntityType.LODGING_STAY
        elif worker == "transport_researcher":
            origin = {"name": "Tokyo Museum", "place_id": "place_origin"}
            transfer = {"name": "Transfer Station", "station_code": "station_transfer"}
            target = {"name": "Tokyo Hotel", "place_id": "place_target"}
            identity = {
                "route_id": f"route_{candidate_id}",
                "selected_mode": "metro",
                "from_endpoint": origin,
                "to_endpoint": target,
                "duration_minutes": 60,
                "segments": [
                    {
                        "segment_id": "segment_1",
                        "mode": "metro",
                        "from_endpoint": origin,
                        "to_endpoint": transfer,
                        "duration_minutes": 40,
                        "departure_at": _NOW.isoformat(),
                    },
                    {
                        "segment_id": "segment_2",
                        "mode": "bus",
                        "from_endpoint": transfer,
                        "to_endpoint": target,
                        "duration_minutes": 20,
                        "arrival_at": (_NOW + timedelta(hours=1)).isoformat(),
                    },
                ],
            }
            entity_type = EntityType.TRANSPORT_LEG
        source_id = f"source_{candidate_id}"
        snapshot = {
            **identity,
            "estimated_cost_cny": 80,
            "padding": "unrelated page section " * 100,
        }
        sources.append(
            SourceRecord(
                source_record_id=source_id,
                source_kind="external_tool",
                title=candidate_id,
                provider_name="fixture",
                canonical_url=f"https://example.com/{candidate_id}",
                public_excerpt="unrelated page section " * 100,
                retrieved_at=_NOW,
                observed_at=_NOW,
                effective_from=_NOW,
                effective_to=_NOW + timedelta(days=7),
                provider_valid_until=_NOW + timedelta(days=1),
                snapshot=snapshot,
                content_hash=canonical_json_hash(snapshot),
                tool_audit_id=f"audit_{candidate_id}",
            )
        )
        entity = EntityRef(entity_type=entity_type, entity_id=candidate_id)
        for field, value in {
            **identity,
            "estimated_cost_cny": 80,
            "accessibility_metadata": {"routes": ["north"]},
        }.items():
            facts.append(
                FactAssertion(
                    fact_assertion_id=f"fact_{candidate_id}_{field}",
                    entity_ref=entity,
                    field_path=field,
                    asserted_value=value,
                    criticality="decision_critical",
                    status="verified",
                    unit="per_visit" if field == "estimated_cost_cny" else None,
                    currency="CNY" if field == "estimated_cost_cny" else None,
                    observed_at=_NOW,
                    effective_from=_NOW,
                    effective_to=_NOW + timedelta(days=7),
                    expires_at=_NOW + timedelta(days=1),
                    source_links=[
                        FactSourceLink(
                            source_record_id=source_id,
                            relation="supports",
                            source_locator=f"fixture.{field}",
                        )
                    ],
                )
            )
        if extra_facts:
            contradictory_id = f"contradictory_{candidate_id}"
            snapshot = {"opening_window": "closed"}
            sources.append(
                SourceRecord(
                    source_record_id=contradictory_id,
                    source_kind="external_web",
                    title="closure notice",
                    provider_name="fixture_web",
                    public_excerpt="closed",
                    retrieved_at=_NOW,
                    content_hash=canonical_json_hash(snapshot),
                    snapshot=snapshot,
                )
            )
            facts.extend(
                [
                    FactAssertion(
                        fact_assertion_id=f"conflict_{candidate_id}",
                        entity_ref=entity,
                        field_path="opening_window",
                        asserted_value="09:00-17:00",
                        criticality="decision_critical",
                        status="conflict",
                        source_links=[
                            FactSourceLink(
                                source_record_id=source_id,
                                relation="supports",
                                source_locator="hours",
                            ),
                            FactSourceLink(
                                source_record_id=contradictory_id,
                                relation="contradicts",
                                source_locator="notice",
                            ),
                        ],
                    ),
                    FactAssertion(
                        fact_assertion_id=f"missing_{candidate_id}",
                        entity_ref=entity,
                        field_path="wheelchair_access",
                        asserted_value=None,
                        criticality="decision_critical",
                        status="missing",
                    ),
                ]
            )
        candidate_facts = [
            fact for fact in facts if fact.entity_ref.entity_id == candidate_id
        ]
        provenance.extend(
            FieldProvenance(
                origin="external_fact",
                entity_ref=entity,
                field_path=fact.field_path,
                reference_ids=[fact.fact_assertion_id],
            )
            for fact in candidate_facts
        )
        candidate_class = {
            "destination_researcher": VisitCandidate,
            "accommodation_researcher": LodgingCandidate,
            "transport_researcher": TransportCandidate,
        }[worker]
        domain_fields = {
            "destination_researcher": {
                "visit_type": "culture",
                "recommended_duration_minutes": 90,
                "estimated_cost_cny": 80,
            },
            "accommodation_researcher": {
                "check_in_date": "2026-10-05",
                "check_out_date": "2026-10-06",
                "nights": 1,
                "availability_status": "needs_confirmation",
            },
            "transport_researcher": {
                "transport_class": "public_transit",
                "booking_status": "not_required",
            },
        }[worker]
        candidates.append(
            candidate_class(
                candidate_id=candidate_id,
                research_packet_id=packet_id,
                destination_id=destination,
                fact_assertion_ids=[fact.fact_assertion_id for fact in candidate_facts],
                source_record_ids=[source_id],
                field_paths=[fact.field_path for fact in candidate_facts],
                weather_sensitivity=WeatherSensitivity(
                    exposure="indoor",
                    rain_sensitivity="low",
                    heat_sensitivity="low",
                    cold_sensitivity="low",
                    wind_sensitivity="low",
                    requires_clear_visibility=False,
                ),
                selection_reasons=["identity verified", "fits visit"],
                tradeoff="fixture",
                freshness_status="stale" if extra_facts else "current",
                **identity,
                **domain_fields,
            )
        )
        discovery.append(
            CandidateDiscoveryRecord(
                candidate_id=candidate_id,
                generation_id=generation,
                query_ids=["query_test"],
                origins=["structural_query"],
                provider_audit_ids=[f"audit_{candidate_id}"],
                discovered_at_rounds=[0],
            )
        )
    return ResearchPacket(
        research_packet_id=packet_id,
        run_id=run_id,
        generation_id=generation,
        intent_spec_revision=1,
        research_query_plan_id="plan_test",
        executed_query_ids=["query_test"],
        candidate_discovery_records=discovery,
        task_id="task_test",
        worker_kind=worker,
        constraint_pack_revision=1,
        fact_data_revision=revision,
        query_context={"large_query": "query prose " * 100},
        candidates=candidates,
        source_records=sources,
        fact_assertions=facts,
        field_provenance=provenance,
        generated_at=_NOW,
    )


def _scope(**overrides):
    return {
        "worker_kind": "accommodation_researcher",
        "run_id": "run_test",
        "generation_id": "generation_test",
        "planned_queries": [_query()],
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
    scope = _scope(planned_queries=[_query(), _query("osaka", "generation_old")])
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
