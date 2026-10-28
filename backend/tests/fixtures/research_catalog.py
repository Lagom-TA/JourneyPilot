from datetime import datetime, timezone

from travel_agent.planning.references import EntityRef, EntityType
from travel_agent.planning.requirements.intent_contracts import (
    CategoryIntentValue,
    IntentItem,
    IntentKind,
    IntentSpec,
    IntentStrength,
    IntentTarget,
    VerificationMode,
    canonical_json_hash,
)
from travel_agent.planning.research.candidates import (
    TransportCandidate,
    VisitCandidate,
)
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.planning.research.discovery_contracts import (
    CandidateDiscoveryOrigin,
    CandidateDiscoveryRecord,
)
from travel_agent.planning.research.evidence import (
    FactAssertion,
    FactSourceLink,
    FieldProvenance,
    SourceRecord,
)
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.planning.transport import (
    TransportEndpoint,
    TransportMode,
    TransportSegment,
)
from travel_agent.planning.weather.models import WeatherSensitivity


def make_research_intent(
    intent_id: str,
    summary: str,
    *,
    kind: IntentKind = IntentKind.THEME,
    strength: IntentStrength = IntentStrength.SOFT,
    priority: int = 90,
    verification: VerificationMode = VerificationMode.SEMANTIC,
) -> IntentItem:
    return IntentItem(
        intent_id=intent_id,
        kind=kind,
        target=IntentTarget.VISIT,
        strength=strength,
        priority=priority,
        value=CategoryIntentValue(categories=[summary]),
        source_kind="current_request",
        source_ref_id=f"source_{intent_id}",
        source_text=summary,
        linked_constraint_ids=[],
        verification_mode=verification,
        impact_stages=["research", "composition"],
        public_summary=summary,
    )

def make_intent_spec(*intents: IntentItem) -> IntentSpec:
    material = [intent.model_dump(mode="json") for intent in intents]
    return IntentSpec(
        intent_spec_id="intent_spec_test",
        revision=1,
        generation_id="generation_test",
        content_hash=canonical_json_hash(material),
        active_items=list(intents),
        objective_summary="Tokyo intent test",
    )

def make_visit_packet(
    candidate_id: str,
    name: str,
    *,
    origin: CandidateDiscoveryOrigin,
    query_id: str,
    intent_id: str,
    opening_window: str | None = None,
) -> ResearchPacket:
    source_id = f"source_{candidate_id}"
    fact_id = f"fact_{candidate_id}"
    source = SourceRecord(
        source_record_id=source_id,
        source_kind="external_tool",
        title=name,
        provider_name="fixture",
        public_excerpt=name,
        retrieved_at=datetime.now(timezone.utc),
        content_hash=canonical_json_hash({"name": name}),
        snapshot={
            "name": name,
            **(
                {"opening_window": opening_window} if opening_window is not None else {}
            ),
        },
        tool_audit_id=f"audit_{candidate_id}",
    )
    fact = FactAssertion(
        fact_assertion_id=fact_id,
        entity_ref=EntityRef(
            entity_type=EntityType.VISIT_STOP,
            entity_id=candidate_id,
        ),
        field_path="name",
        asserted_value=name,
        criticality="decision_critical",
        status="verified",
        source_links=[
            FactSourceLink(
                source_record_id=source_id,
                relation="supports",
                source_locator="fixture.name",
            )
        ],
    )
    facts = [fact]
    if opening_window is not None:
        facts.append(
            FactAssertion(
                fact_assertion_id=f"{fact_id}_opening_window",
                entity_ref=fact.entity_ref,
                field_path="opening_window",
                asserted_value=opening_window,
                criticality="decision_critical",
                status="verified",
                source_links=[
                    FactSourceLink(
                        source_record_id=source_id,
                        relation="supports",
                        source_locator="fixture.opening_window",
                    )
                ],
            )
        )
    candidate = VisitCandidate(
        candidate_id=candidate_id,
        research_packet_id=f"packet_{candidate_id}",
        destination_id="destination_tokyo",
        fact_assertion_ids=[item.fact_assertion_id for item in facts],
        source_record_ids=[source_id],
        field_paths=[item.field_path for item in facts],
        weather_sensitivity=WeatherSensitivity(
            exposure="mixed",
            rain_sensitivity="low",
            heat_sensitivity="low",
            cold_sensitivity="low",
            wind_sensitivity="low",
            requires_clear_visibility=False,
        ),
        selection_reasons=["verified identity", "intent candidate"],
        tradeoff="fixture",
        freshness_status="current",
        place_id=f"place_{candidate_id}",
        provider_place_type="tourism;attraction",
        provider_country_code="JP",
        name=name,
        address="Tokyo",
        visit_type="culture",
        recommended_duration_minutes=90,
        opening_window=opening_window,
    )
    record = CandidateDiscoveryRecord(
        candidate_id=candidate_id,
        generation_id="generation_test",
        query_ids=[query_id],
        intent_ids=[intent_id],
        origins=[origin],
        provider_audit_ids=[f"audit_{candidate_id}"],
        discovered_at_rounds=[0],
    )
    return ResearchPacket(
        research_packet_id=f"packet_{candidate_id}",
        run_id="run_test",
        generation_id="generation_test",
        intent_spec_revision=1,
        research_query_plan_id="query_plan_generation_test",
        executed_query_ids=[query_id],
        candidate_discovery_records=[record],
        task_id=f"task_{candidate_id}",
        worker_kind="destination_researcher",
        constraint_pack_revision=1,
        fact_data_revision=1,
        query_context={},
        candidates=[candidate],
        source_records=[source],
        fact_assertions=facts,
        field_provenance=[
            FieldProvenance(
                origin="external_fact",
                entity_ref=item.entity_ref,
                field_path=item.field_path,
                reference_ids=[item.fact_assertion_id],
            )
            for item in facts
        ],
        generated_at=datetime.now(timezone.utc),
    )

def make_catalog(*packets: ResearchPacket) -> RecommendationCatalog:
    return RecommendationCatalog(
        generation_id="generation_test",
        intent_spec_revision=1,
        research_query_plan_id="query_plan_generation_test",
        fact_data_revision=1,
        weather_data_revision=0,
        research_packets=list(packets),
        candidate_discovery_records=[
            record
            for packet in packets
            for record in packet.candidate_discovery_records
        ],
    )

def make_local_transport_packet(
    candidate_id: str,
    *,
    origin_place_id: str,
    destination_place_id: str,
) -> ResearchPacket:
    packet = make_visit_packet(
        candidate_id,
        f"{origin_place_id} to {destination_place_id}",
        origin=CandidateDiscoveryOrigin.STRUCTURAL_QUERY,
        query_id=f"query_{candidate_id}",
        intent_id="intent_transport",
    )
    from_endpoint = TransportEndpoint(
        name=origin_place_id,
        place_id=origin_place_id,
    )
    to_endpoint = TransportEndpoint(
        name=destination_place_id,
        place_id=destination_place_id,
    )
    segment = TransportSegment(
        segment_id=f"segment_{candidate_id}",
        mode=TransportMode.BUS,
        from_endpoint=from_endpoint,
        to_endpoint=to_endpoint,
        duration_minutes=20,
    )
    candidate = TransportCandidate(
        candidate_id=candidate_id,
        research_packet_id=packet.research_packet_id,
        destination_id="destination_tokyo",
        fact_assertion_ids=[f"fact_{candidate_id}"],
        source_record_ids=[f"source_{candidate_id}"],
        field_paths=["segments"],
        weather_sensitivity=WeatherSensitivity(
            exposure="mixed",
            rain_sensitivity="low",
            heat_sensitivity="low",
            cold_sensitivity="low",
            wind_sensitivity="low",
            requires_clear_visibility=False,
        ),
        selection_reasons=["exact endpoints", "provider route"],
        tradeoff="fixture",
        freshness_status="current",
        route_id=f"route_{candidate_id}",
        transport_class="public_transit",
        # 本地连接的身份由有向端点对确定；与长途责任不同，它不携带大范围 scope id。
        provider_evidence_scope_id=None,
        selected_mode=TransportMode.BUS,
        from_endpoint=from_endpoint,
        to_endpoint=to_endpoint,
        duration_minutes=20,
        segments=[segment],
        booking_status="not_required",
    )
    return packet.model_copy(
        update={
            "worker_kind": "transport_researcher",
            "candidates": [candidate],
        }
    )
