from __future__ import annotations

from datetime import datetime, timedelta, timezone

from travel_agent.planning.references import EntityRef, EntityType
from travel_agent.planning.requirements.intent_contracts import canonical_json_hash
from travel_agent.planning.research.candidates import (
    LodgingCandidate,
    TransportCandidate,
    VisitCandidate,
)
from travel_agent.planning.research.discovery_contracts import CandidateDiscoveryRecord
from travel_agent.planning.research.evidence import (
    FactAssertion,
    FactSourceLink,
    FieldProvenance,
    SourceRecord,
)
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.planning.research.query_contracts import ResearchQuery
from travel_agent.planning.weather.models import WeatherSensitivity

RESEARCH_TIME = datetime(2026, 10, 5, 10, tzinfo=timezone.utc)

def make_research_query(destination="tokyo", generation="generation_test", query_id="query_test"):
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
                        "departure_at": RESEARCH_TIME.isoformat(),
                    },
                    {
                        "segment_id": "segment_2",
                        "mode": "bus",
                        "from_endpoint": transfer,
                        "to_endpoint": target,
                        "duration_minutes": 20,
                        "arrival_at": (RESEARCH_TIME + timedelta(hours=1)).isoformat(),
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
                retrieved_at=RESEARCH_TIME,
                observed_at=RESEARCH_TIME,
                effective_from=RESEARCH_TIME,
                effective_to=RESEARCH_TIME + timedelta(days=7),
                provider_valid_until=RESEARCH_TIME + timedelta(days=1),
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
                    observed_at=RESEARCH_TIME,
                    effective_from=RESEARCH_TIME,
                    effective_to=RESEARCH_TIME + timedelta(days=7),
                    expires_at=RESEARCH_TIME + timedelta(days=1),
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
                    retrieved_at=RESEARCH_TIME,
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
        generated_at=RESEARCH_TIME,
    )
