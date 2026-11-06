"""把交通工具返回的路线编译为带来源的研究成果。"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from travel_agent.planning.itinerary.connectors import LocalConnectorGap
from travel_agent.planning.nodes import NODE_ITINERARY
from travel_agent.planning.references import EntityRef, EntityType
from travel_agent.planning.research.candidates import TransportCandidate
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.planning.research.evidence import (
    FactAssertion,
    FactSourceLink,
    FieldProvenance,
    SourceRecord,
)
from travel_agent.planning.research.output.identifiers import (
    _canonical_snapshot_hash,
    _provider_candidate_id,
    _provider_fact_id,
    _provider_route_source_id,
)
from travel_agent.planning.research.output.sources import (
    _provider_snapshot_source_fields,
)
from travel_agent.planning.research.output.transcript import (
    _successful_route_records,
    authoritative_tool_messages,
)
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.planning.state import TravelAgentState
_PROVIDER_ROUTE_FIELDS = (
    "route_id",
    "transport_class",
    "selected_mode",
    "from_endpoint",
    "to_endpoint",
    "boarding_stop",
    "alighting_stop",
    "departure_at",
    "arrival_at",
    "duration_minutes",
    "distance_meters",
    "total_cost_cny",
    "segments",
)


def _route_packet(
    *,
    state: TravelAgentState,
    catalog: RecommendationCatalog,
    gap: LocalConnectorGap | None,
    envelope: Mapping[str, Any],
    existing_candidate_ids: set[str],
    destination_id: str | None = None,
    task_id: str | None = None,
    route_ids: set[str] | None = None,
) -> Optional[ResearchPacket]:
    """只把 Gateway 允许作为证据的 Provider 路线编译成类型化数据包。"""
    generated_at = datetime.now(timezone.utc)
    records = _successful_route_records(authoritative_tool_messages([envelope]))
    candidates: list[TransportCandidate] = []
    sources: list[SourceRecord] = []
    facts: list[FactAssertion] = []
    provenance: list[FieldProvenance] = []
    added_candidate_ids: set[str] = set()
    target_id = gap.gap_id if gap is not None else str(task_id or "transport_followup")
    packet_target = f"{target_id}\0{','.join(sorted(route_ids or []))}" if route_ids else target_id
    resolved_destination = gap.destination_id if gap is not None else str(destination_id or "")
    if not resolved_destination:
        return None
    packet_digest = hashlib.sha256(
        f"{state.run_id}\0{packet_target}\0{envelope.get('audit_id', '')}".encode(
            "utf-8"
        )
    ).hexdigest()[:20]
    packet_id = f"packet_transport_connector_{packet_digest}"

    for route_id, (route_envelope, route, route_index) in records.items():
        if route_ids is not None and route_id not in route_ids:
            continue
        if route["transport_class"] == "long_distance":
            continue
        candidate_id = _provider_candidate_id("transport", route_id)
        if candidate_id in existing_candidate_ids or candidate_id in added_candidate_ids:
            continue
        audit_id = str(route_envelope["audit_id"])
        source_id = _provider_route_source_id(audit_id, route_id)
        result = route_envelope.get("sanitized_result") or {}
        (
            snapshot,
            cache_provenance,
            observed_at,
            retrieved_at,
            provider_valid_until,
        ) = _provider_snapshot_source_fields(
            route_envelope,
            fallback_observed_at=generated_at,
        )
        provider_name = str(
            result.get("provider")
            or route_envelope.get("server_name")
            or "global_route_search"
        )
        source = SourceRecord(
            source_record_id=source_id,
            source_kind="external_tool",
            title=f"{provider_name} route: {route_id}",
            provider_name=provider_name,
            public_excerpt=(
                f"{route['from_endpoint']['name']} → "
                f"{route['to_endpoint']['name']} · {route['duration_minutes']} 分钟"
            )[:900],
            retrieved_at=retrieved_at,
            observed_at=observed_at,
            provider_valid_until=provider_valid_until,
            content_hash=(
                cache_provenance.content_hash
                if cache_provenance is not None
                else _canonical_snapshot_hash(snapshot)
            ),
            snapshot=snapshot,
            tool_audit_id=audit_id,
            cache_provenance=cache_provenance,
        )
        entity_ref = EntityRef(
            entity_type=EntityType.TRANSPORT_LEG,
            entity_id=candidate_id,
        )
        route_facts: list[FactAssertion] = []
        route_provenance: list[FieldProvenance] = []
        for field_path in _PROVIDER_ROUTE_FIELDS:
            asserted_value = route.get(field_path)
            if asserted_value is None:
                continue
            fact_id = _provider_fact_id(audit_id, candidate_id, field_path)
            route_facts.append(
                FactAssertion(
                    fact_assertion_id=fact_id,
                    entity_ref=entity_ref,
                    field_path=field_path,
                    asserted_value=asserted_value,
                    criticality="execution_critical",
                    status="verified",
                    observed_at=observed_at,
                    source_links=[
                        FactSourceLink(
                            source_record_id=source_id,
                            relation="supports",
                            source_locator=(
                                f"routes[{route_index}].{field_path}"
                                if cache_provenance is not None
                                else "sanitized_result."
                                f"routes[{route_index}].{field_path}"
                            ),
                        )
                    ],
                )
            )
            route_provenance.append(
                FieldProvenance(
                    origin="external_fact",
                    entity_ref=entity_ref,
                    field_path=field_path,
                    reference_ids=[fact_id],
                )
            )
        candidate = TransportCandidate(
            candidate_id=candidate_id,
            research_packet_id=packet_id,
            destination_id=resolved_destination,
            fact_assertion_ids=[fact.fact_assertion_id for fact in route_facts],
            source_record_ids=[source_id],
            field_paths=[fact.field_path for fact in route_facts],
            weather_sensitivity={
                "exposure": "mixed",
                "rain_sensitivity": "low",
                "heat_sensitivity": "low",
                "cold_sensitivity": "low",
                "wind_sensitivity": "low",
                "requires_clear_visibility": False,
            },
            selection_reasons=["精确相邻接驳缺口的定向 Provider 路线"],
            tradeoff="保留 Provider 返回路线，由现有接驳匹配逻辑选择",
            freshness_status="current",
            observed_at=observed_at,
            route_id=route_id,
            transport_class=route["transport_class"],
            selected_mode=route["selected_mode"],
            from_endpoint=route["from_endpoint"],
            to_endpoint=route["to_endpoint"],
            boarding_stop=route.get("boarding_stop"),
            alighting_stop=route.get("alighting_stop"),
            departure_at=route.get("departure_at"),
            arrival_at=route.get("arrival_at"),
            duration_minutes=route["duration_minutes"],
            distance_meters=route.get("distance_meters"),
            total_cost_cny=route.get("total_cost_cny"),
            segments=route["segments"],
            booking_status=route.get("booking_status") or "not_required",
        )
        candidates.append(candidate)
        sources.append(source)
        facts.extend(route_facts)
        provenance.extend(route_provenance)
        added_candidate_ids.add(candidate_id)

    if not candidates:
        return None
    return ResearchPacket(
        research_packet_id=packet_id,
        run_id=state.run_id,
        generation_id=catalog.generation_id,
        task_id=f"{NODE_ITINERARY}:{target_id}",
        worker_kind="transport_researcher",
        fact_data_revision=catalog.fact_data_revision,
        query_context={
            "connector_gap_id": gap.gap_id if gap is not None else None,
            "activation_source": "transport_followup",
        },
        candidates=candidates,
        source_records=sources,
        fact_assertions=facts,
        field_provenance=provenance,
        generated_at=generated_at,
    )
