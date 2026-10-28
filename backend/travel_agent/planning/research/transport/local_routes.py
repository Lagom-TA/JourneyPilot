"""为落位产生的本地接驳缺口定向补查 Provider 路线。"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from travel_agent.planning.itinerary.connectors import LocalConnectorGap
from travel_agent.planning.nodes import NODE_ITINERARY
from travel_agent.planning.references import EntityRef, EntityType
from travel_agent.planning.research.candidates import TransportCandidate
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
from travel_agent.planning.research.transport.endpoints import (
    _routable_connector_endpoints,
)
from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.tool_context import build_tool_context_from_state
from travel_agent.planning.transport_semantics import provider_route_mode
from travel_agent.tools.execution import execute_tool
from travel_agent.tools.registry import get_tool_registry

logger = logging.getLogger(__name__)


_LOCAL_ROUTE_TOOL_NAMES = frozenset({"global_route_search"})
_DIRECT_ROUTE_MODES = frozenset({"walk", "bike", "drive"})
_PROVIDER_ROUTE_FIELDS = (
    "route_id",
    "transport_class",
    "selected_mode",
    "from_endpoint",
    "to_endpoint",
    "departure_at",
    "arrival_at",
    "duration_minutes",
    "distance_meters",
    "total_cost_cny",
    "segments",
)


def _connector_request(
    gap: LocalConnectorGap,
    endpoints: Mapping[tuple[str, str], Mapping[str, Any]],
) -> Optional[dict[str, Any]]:
    origin = endpoints.get((gap.from_place_id, gap.destination_id))
    destination = endpoints.get((gap.to_place_id, gap.destination_id))
    if origin is None or destination is None:
        return None
    if gap.preferred_transport_class == "public_transit":
        mode = "public_transit"
    else:
        mode = next(
            (
                provider_route_mode(requested)
                for requested in gap.requested_flexible_modes
                if provider_route_mode(requested) in _DIRECT_ROUTE_MODES
            ),
            None,
        )
    if mode is None:
        logger.info(
            "[connector] gap %s has no global_route_search-compatible mode",
            gap.gap_id,
        )
        return None
    return {
        "from_name": origin["name"],
        "from_place_id": origin["place_id"],
        "from_latitude": origin["latitude"],
        "from_longitude": origin["longitude"],
        "to_name": destination["name"],
        "to_place_id": destination["place_id"],
        "to_latitude": destination["latitude"],
        "to_longitude": destination["longitude"],
        "departure_time": gap.departure_time.isoformat(),
        "mode": mode,
    }


def _route_packet(
    *,
    state: TravelAgentState,
    catalog: RecommendationCatalog,
    gap: LocalConnectorGap,
    envelope: Mapping[str, Any],
    existing_candidate_ids: set[str],
) -> Optional[ResearchPacket]:
    """只把 Gateway 允许作为证据的 Provider 路线编译成类型化数据包。"""
    generated_at = datetime.now(timezone.utc)
    records = _successful_route_records(authoritative_tool_messages([envelope]))
    candidates: list[TransportCandidate] = []
    sources: list[SourceRecord] = []
    facts: list[FactAssertion] = []
    provenance: list[FieldProvenance] = []
    discoveries: list[CandidateDiscoveryRecord] = []
    added_candidate_ids: set[str] = set()
    packet_digest = hashlib.sha256(
        f"{state.run_id}\0{gap.gap_id}\0{envelope.get('audit_id', '')}".encode(
            "utf-8"
        )
    ).hexdigest()[:20]
    packet_id = f"packet_transport_connector_{packet_digest}"

    for route_id, (route_envelope, route, route_index) in records.items():
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
                f"{route['to_endpoint']['name']} · {route['duration_minutes']} min"
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
            destination_id=gap.destination_id,
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
        discoveries.append(
            CandidateDiscoveryRecord(
                candidate_id=candidate_id,
                generation_id=catalog.generation_id,
                origins=[CandidateDiscoveryOrigin.TARGETED_REPAIR],
                provider_audit_ids=[audit_id],
                discovered_at_rounds=[0],
            )
        )
        added_candidate_ids.add(candidate_id)

    if not candidates:
        return None
    return ResearchPacket(
        research_packet_id=packet_id,
        run_id=state.run_id,
        generation_id=catalog.generation_id,
        intent_spec_revision=catalog.intent_spec_revision,
        research_query_plan_id=catalog.research_query_plan_id,
        candidate_discovery_records=discoveries,
        task_id=f"{NODE_ITINERARY}:{gap.gap_id}",
        worker_kind="transport_researcher",
        constraint_pack_revision=state.constraint_pack_revision,
        fact_data_revision=catalog.fact_data_revision,
        query_context={
            "connector_gap_id": gap.gap_id,
            "activation_source": "local_connector_route_completion",
        },
        candidates=candidates,
        source_records=sources,
        fact_assertions=facts,
        field_provenance=provenance,
        generated_at=generated_at,
    )


async def complete_local_connector_routes(
    state: TravelAgentState,
    gaps: list[LocalConnectorGap],
) -> RecommendationCatalog:
    """每个可路由缺口只查询一次，并把 Provider 证据追加到候选目录。"""
    catalog = state.recommendation_catalog
    if catalog is None:
        raise ValueError("local connector completion requires the candidate catalog")
    if not gaps or not get_tool_registry().has_tool("global_route_search"):
        return catalog

    endpoints = {
        (endpoint["place_id"], endpoint["destination_id"]): endpoint
        for endpoint in _routable_connector_endpoints(state)
    }
    tool_context = build_tool_context_from_state(state)
    existing_candidate_ids = set(catalog.candidate_index())
    additions: list[ResearchPacket] = []
    for gap in gaps:
        request = _connector_request(gap, endpoints)
        if request is None:
            logger.info(
                "[connector] gap %s has no routable coordinate endpoints; "
                "keeping authored fallback",
                gap.gap_id,
            )
            continue
        envelope = await execute_tool(
            "global_route_search",
            request,
            allowed_tool_names=_LOCAL_ROUTE_TOOL_NAMES,
            max_retries=0,
            node_name=NODE_ITINERARY,
            activation_source="local_connector_route_completion",
            allow_fallback=False,
            **tool_context,
        )
        try:
            packet = _route_packet(
                state=state,
                catalog=catalog,
                gap=gap,
                envelope=envelope,
                existing_candidate_ids=existing_candidate_ids,
            )
        except (TypeError, ValueError) as exc:
            logger.warning(
                "[connector] gap %s Provider route evidence was not usable: %s",
                gap.gap_id,
                exc,
            )
            continue
        if packet is not None:
            additions.append(packet)
            existing_candidate_ids.update(
                candidate.candidate_id for candidate in packet.candidates
            )

    if not additions:
        return catalog
    packets = [*catalog.research_packets, *additions]
    return RecommendationCatalog(
        generation_id=catalog.generation_id,
        intent_spec_revision=catalog.intent_spec_revision,
        research_query_plan_id=catalog.research_query_plan_id,
        fact_data_revision=catalog.fact_data_revision,
        weather_data_revision=catalog.weather_data_revision,
        research_packets=packets,
        candidate_discovery_records=[
            record for packet in packets for record in packet.candidate_discovery_records
        ],
    )
