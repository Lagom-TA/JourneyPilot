"""把补查取得的 12306 班次编译为可引用的长途候选。"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from typing import Any, Mapping

from travel_agent.integrations.rail.stations import station_table
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
from travel_agent.planning.research.output.sources import _provider_snapshot_source_fields
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.planning.research.transport.rail.binding import _build_rail_route_envelope
from travel_agent.planning.research.transport.rail.parsing import (
    _indexed_rail_train_records,
    _normalize_cn_city_for_rail,
)
from travel_agent.planning.research.transport.rail.selection import _select_best_train
from travel_agent.planning.state import TravelAgentState

_MAX_OPTIONS = 3


def _rail_destination_id(
    state: TravelAgentState,
    train: Mapping[str, Any],
    *,
    destination_id: str,
    from_destination_id: str,
    to_destination_id: str,
) -> str:
    """优先按实际到站所属城市归属，返程则使用相关的行程目的地。"""
    destinations = {
        str(item.get("place_id") or ""): item
        for item in state.controlled_trip_identity.get("destinations", [])
        if isinstance(item, Mapping) and item.get("place_id")
    }
    stations = station_table()
    for end in ("to", "from"):
        station = stations.get(str(train.get(f"{end}_code") or ""))
        city = _normalize_cn_city_for_rail(station.city) if station else ""
        name = _normalize_cn_city_for_rail(str(train.get(f"{end}_name") or ""))
        for place_id, place in destinations.items():
            place_name = _normalize_cn_city_for_rail(str(place.get("name") or ""))
            if place_name and place_name in {city, name}:
                return place_id
        if end == "to" and to_destination_id in destinations:
            return to_destination_id
    known_ids = set(destinations)
    if state.recommendation_catalog is not None:
        known_ids.update(
            candidate.destination_id
            for candidate in state.recommendation_catalog.candidate_index().values()
        )
    for place_id in (destination_id, from_destination_id):
        if place_id in known_ids:
            return place_id
    return next(iter(known_ids)) if len(known_ids) == 1 else ""


def _matching_rail_scope(
    catalog: RecommendationCatalog, train: Mapping[str, Any], travel_date: str, arrival_date: str,
) -> str | None:
    """同日同方向且到达日期相同的铁路候选可以共享交通备选范围。"""
    stations = station_table()

    def same_city(left: str | None, right: str) -> bool:
        if left == right:
            return True
        a, b = stations.get(left or ""), stations.get(right)
        return bool(a and b and a.city and a.city == b.city)

    matches = {
        candidate.provider_evidence_scope_id
        for candidate in catalog.candidate_index().values()
        if isinstance(candidate, TransportCandidate)
        and candidate.transport_class == "long_distance"
        and candidate.selected_mode.value in {"train", "high_speed_rail"}
        and candidate.provider_evidence_scope_id
        and candidate.departure_at is not None
        and candidate.arrival_at is not None
        and candidate.departure_at.date().isoformat() == travel_date
        and candidate.arrival_at.date().isoformat() == arrival_date
        and same_city(candidate.from_endpoint.station_code, str(train["from_code"]))
        and same_city(candidate.to_endpoint.station_code, str(train["to_code"]))
    }
    return next(iter(matches)) if len(matches) == 1 else None


def compile_rail_followup_packet(
    *,
    state: TravelAgentState,
    catalog: RecommendationCatalog,
    envelope: Mapping[str, Any],
    task_id: str,
    existing_candidate_ids: set[str],
    destination_id: str = "",
    from_destination_id: str = "",
    to_destination_id: str = "",
    service_date: str = "",
    matched_candidate_ids: set[str] | None = None,
) -> ResearchPacket | None:
    """编译真实班次；通过 ``matched_candidate_ids`` 返回已收录的候选标识。"""
    metadata = envelope.get("metadata") or {}
    result = envelope.get("sanitized_result")
    audit_id = str(envelope.get("audit_id") or "")
    if (
        envelope.get("tool_name") != "get-tickets"
        or envelope.get("status") != "success"
        or not isinstance(metadata, Mapping)
        or metadata.get("evidence_allowed") is not True
        or metadata.get("quarantine_result")
        or not audit_id
        or not isinstance(result, Mapping)
        or result.get("success") is not True
    ):
        return None
    result_date = str(result.get("date") or "")[:10]
    if result_date and service_date and result_date != service_date[:10]:
        return None
    route_leg = metadata.get("rail_route_leg")
    if (
        isinstance(route_leg, Mapping)
        and result_date
        and str(route_leg.get("service_date") or "") != result_date
    ):
        return None
    try:
        travel_date = date.fromisoformat(result_date or service_date[:10]).isoformat()
    except ValueError:
        return None

    indexed = _indexed_rail_train_records(envelope)
    selected = metadata.get("rail_selected_train")
    if isinstance(selected, Mapping):
        indexed = [
            (index, train) for index, train in indexed
            if all(train.get(key) == selected.get(key) for key in ("train_code", "from_code", "to_code"))
        ]
    source_envelope = dict(envelope)
    source_metadata = {
        key: value for key, value in metadata.items() if not key.startswith("rail_")
    }
    source_envelope["metadata"] = source_metadata
    generated_at = datetime.now(timezone.utc)
    snapshot, cache, observed_at, retrieved_at, valid_until = _provider_snapshot_source_fields(
        source_envelope, fallback_observed_at=generated_at
    )
    packet_digest = hashlib.sha256(f"{state.run_id}\0{task_id}\0{audit_id}".encode()).hexdigest()[:20]
    packet_id = f"packet_transport_rail_{packet_digest}"
    candidates: list[TransportCandidate] = []
    sources: list[SourceRecord] = []
    facts: list[FactAssertion] = []
    provenance: list[FieldProvenance] = []
    added_ids = set(existing_candidate_ids)
    catalog_by_route = {
        candidate.route_id: candidate.candidate_id
        for candidate in catalog.candidate_index().values()
        if isinstance(candidate, TransportCandidate) and candidate.transport_class == "long_distance"
    }

    while indexed and len(candidates) < _MAX_OPTIONS:
        best = _select_best_train(
            [train for _, train in indexed],
            requested_from=str(result.get("from_station") or ""),
            requested_to=str(result.get("to_station") or ""),
            leg_role="inter_destination",
        )
        if best is None:
            break
        index = next(i for i, (_, train) in enumerate(indexed) if train is best)
        row_index, train = indexed.pop(index)
        try:
            route = _build_rail_route_envelope(
                train=train, start_date=travel_date, audit_id=audit_id,
                retrieved_at=str(envelope.get("retrieved_at") or generated_at.isoformat()),
                from_point=metadata.get("rail_from_point"),
                to_point=metadata.get("rail_to_point"),
            )["sanitized_result"]["routes"][0]
        except (TypeError, ValueError):
            continue
        resolved_destination = _rail_destination_id(
            state, train, destination_id=destination_id,
            from_destination_id=from_destination_id or (
                str(route_leg.get("from_place_id") or "") if isinstance(route_leg, Mapping) else ""
            ),
            to_destination_id=to_destination_id or (
                str(route_leg.get("to_place_id") or "") if isinstance(route_leg, Mapping) else ""
            ),
        )
        if not resolved_destination:
            continue
        route_id = f"12306:{travel_date}:{train['train_code']}:{train['from_code']}:{train['to_code']}"
        candidate_id = _provider_candidate_id("transport", route_id)
        existing_id = catalog_by_route.get(route_id)
        if existing_id or candidate_id in added_ids:
            if matched_candidate_ids is not None:
                matched_candidate_ids.add(existing_id or candidate_id)
            continue
        try:
            route["route_id"] = route_id
            if isinstance(selected, Mapping):
                scope_id = str(metadata.get("rail_scope_id") or "") or None
                if (
                    isinstance(route_leg, Mapping)
                    and route_leg.get("cross_day_required")
                    and route["departure_at"][:10] == route["arrival_at"][:10]
                ):
                    scope_id = None
            else:
                scope_id = _matching_rail_scope(catalog, train, travel_date, route["arrival_at"][:10])
            candidate = TransportCandidate(
                candidate_id=candidate_id,
                research_packet_id=packet_id,
                destination_id=resolved_destination,
                weather_sensitivity={
                    "exposure": "mixed", "rain_sensitivity": "low", "heat_sensitivity": "low",
                    "cold_sensitivity": "low", "wind_sensitivity": "low",
                    "requires_clear_visibility": False,
                },
                selection_reasons=["12306 查询到的可购班次"],
                tradeoff="保留查询时的班次和票价",
                freshness_status="current",
                observed_at=observed_at,
                route_id=route_id,
                transport_class="long_distance",
                provider_evidence_scope_id=scope_id,
                selected_mode=route["selected_mode"],
                from_endpoint=route["from_endpoint"],
                to_endpoint=route["to_endpoint"],
                departure_at=route["departure_at"],
                arrival_at=route["arrival_at"],
                duration_minutes=route["duration_minutes"],
                total_cost_cny=route.get("total_cost_cny"),
                segments=route["segments"],
                booking_status="required",
            )
        except (TypeError, ValueError):
            continue
        source_id = _provider_route_source_id(audit_id, route_id)
        provider = str(result.get("provider") or "12306")
        sources.append(SourceRecord(
            source_record_id=source_id,
            source_kind="external_tool",
            title=f"{provider} 车次查询：{train['train_code']}",
            provider_name=provider,
            public_excerpt=(f"{train['train_code']} {train['from_name']} → {train['to_name']} "
                            f"{train['departure_time']}–{train['arrival_time']}")[:900],
            retrieved_at=retrieved_at,
            observed_at=observed_at,
            provider_valid_until=valid_until,
            content_hash=cache.content_hash if cache is not None else _canonical_snapshot_hash(snapshot),
            snapshot=snapshot,
            tool_audit_id=audit_id,
            cache_provenance=cache,
        ))
        entity_ref = EntityRef(entity_type=EntityType.TRANSPORT_LEG, entity_id=candidate_id)
        prefix = "" if cache is not None else "sanitized_result."
        row_path = f"{prefix}results[{row_index}]"
        fields = {
            "route_id": None,
            "transport_class": "train_code",
            "selected_mode": "train_code",
            "from_endpoint": None,
            "to_endpoint": None,
            "departure_at": "departure_time",
            "arrival_at": "arrival_time",
            "duration_minutes": "duration_minutes",
            "total_cost_cny": "min_price_cny",
            "segments": None,
        }
        for field, row_field in fields.items():
            value = route.get(field)
            if value is None:
                continue
            fact_id = _provider_fact_id(audit_id, candidate_id, field)
            links = [FactSourceLink(
                source_record_id=source_id, relation="supports",
                source_locator=f"{row_path}.{row_field}" if row_field else row_path,
            )]
            if field in {"route_id", "departure_at", "arrival_at", "segments"} and result.get("date"):
                links.append(FactSourceLink(
                    source_record_id=source_id, relation="supports", source_locator=f"{prefix}date",
                ))
            facts.append(FactAssertion(
                fact_assertion_id=fact_id, entity_ref=entity_ref, field_path=field,
                asserted_value=value, criticality="execution_critical", status="verified",
                observed_at=observed_at, source_links=links,
            ))
            provenance.append(FieldProvenance(
                origin="external_fact", entity_ref=entity_ref, field_path=field, reference_ids=[fact_id],
            ))
        candidates.append(candidate)
        added_ids.add(candidate_id)

    if not candidates:
        return None
    return ResearchPacket(
        research_packet_id=packet_id,
        run_id=state.run_id,
        generation_id=catalog.generation_id,
        task_id=f"{NODE_ITINERARY}:{task_id}",
        worker_kind="transport_researcher",
        fact_data_revision=catalog.fact_data_revision,
        query_context={"activation_source": "transport_followup", "service_date": travel_date},
        candidates=candidates,
        source_records=sources,
        fact_assertions=facts,
        field_provenance=provenance,
        generated_at=generated_at,
    )
