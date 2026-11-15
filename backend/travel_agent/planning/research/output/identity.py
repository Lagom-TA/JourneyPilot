from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Mapping, Sequence

from pydantic import ValidationError

from travel_agent.planning.references import EntityRef, EntityType
from travel_agent.planning.research.evidence import (
    FactAssertion,
    FactSourceLink,
    FieldProvenance,
    SourceRecord,
)
from travel_agent.planning.research.provider_contracts import ProviderEvidenceScope
from travel_agent.planning.transport import TransportEndpoint, TransportSegment
from travel_agent.integrations.places.taxonomy import provider_place_type_matches_candidate_kind

from .identifiers import (
    _canonical_snapshot_hash,
    _provider_entity_source_id,
    _provider_fact_id,
    _provider_route_source_id,
)
from .metadata import _payload_generated_at
from .policy import _PLACE_ENTITY_TYPE, _PLACE_IDENTITY_FIELDS, _PLACE_NAME_FIELD
from .sources import (
    _provider_place_source_payload,
    _provider_snapshot_source_fields,
    _remove_fact_references,
)
from .transcript import _successful_place_records, _successful_route_records

logger = logging.getLogger(__name__)


def _provider_coordinate_pair(
    provider_place: Mapping[str, Any],
) -> tuple[float, float] | None:
    """从 Provider 地点记录中提取有效的 (纬度, 经度)，无效时返回 None。"""
    latitude = provider_place.get("latitude")
    longitude = provider_place.get("longitude")
    if (
        isinstance(latitude, bool)
        or isinstance(longitude, bool)
        or not isinstance(latitude, (int, float))
        or not isinstance(longitude, (int, float))
    ):
        return None
    latitude = float(latitude)
    longitude = float(longitude)
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return None
    return latitude, longitude


def _bind_successful_place_identity(
    payload: dict[str, Any],
    context_messages: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """把 Provider 身份绑定到 worker 选中的地点，但不代替 worker 做选择。"""
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return {}
    records = _successful_place_records(context_messages)
    if not records:
        return {}
    generated_at = payload.get("generated_at")
    existing_facts = payload.get("fact_assertions")
    facts = list(existing_facts) if isinstance(existing_facts, list) else []
    existing_provenance = payload.get("field_provenance")
    provenance = (
        list(existing_provenance) if isinstance(existing_provenance, list) else []
    )
    existing_sources = payload.get("source_records")
    sources = list(existing_sources) if isinstance(existing_sources, list) else []
    bound_sources: dict[str, dict[str, Any]] = {}
    contradicted_places: dict[str, str] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        candidate_kind = str(candidate.get("candidate_kind") or "")
        identity_fields = _PLACE_IDENTITY_FIELDS.get(candidate_kind)
        candidate_id = str(candidate.get("candidate_id") or "").strip()
        place_id = str(candidate.get("place_id") or "").strip()
        record = records.get(place_id)
        if not identity_fields or not candidate_id or record is None:
            continue
        envelope, provider_place, result_index = record
        provider_type = str(provider_place["provider_place_type"])
        if not provider_place_type_matches_candidate_kind(
            provider_type,
            candidate_kind,
        ):
            contradicted_places[candidate_id] = place_id
            continue
        audit_id = str(envelope.get("audit_id") or "").strip()
        if not audit_id:
            continue
        source_id = _provider_entity_source_id(audit_id, place_id)
        (
            _snapshot,
            cache_provenance,
            observed_at,
            _retrieved_at,
            _provider_valid_until,
        ) = _provider_snapshot_source_fields(
            envelope,
            fallback_observed_at=generated_at,
        )
        bound_sources[source_id] = _provider_place_source_payload(
            envelope,
            provider_place,
            fallback_observed_at=generated_at,
        )
        provider_values = {
            _PLACE_NAME_FIELD[candidate_kind]: provider_place["name"],
            "place_id": provider_place["place_id"],
            "provider_place_type": provider_place["provider_place_type"],
            "provider_country_code": provider_place["provider_country_code"],
            "address": provider_place["address"],
        }
        candidate.update(provider_values)
        candidate["freshness_status"] = "current"
        candidate["observed_at"] = observed_at
        coordinate_pair = _provider_coordinate_pair(provider_place)
        replaced_field_paths = set(identity_fields)
        if coordinate_pair is not None:
            replaced_field_paths.update(("latitude", "longitude"))
        replaced_fact_ids = {
            str(fact.get("fact_assertion_id") or "")
            for fact in facts
            if isinstance(fact, dict)
            and (fact.get("entity_ref") or {}).get("entity_id") == candidate_id
            and fact.get("field_path") in replaced_field_paths
        }
        facts = [
            fact
            for fact in facts
            if not (
                isinstance(fact, dict)
                and (fact.get("entity_ref") or {}).get("entity_id") == candidate_id
                and fact.get("field_path") in replaced_field_paths
            )
        ]
        provenance = [
            item
            for item in provenance
            if not (
                isinstance(item, dict)
                and (item.get("entity_ref") or {}).get("entity_id") == candidate_id
                and item.get("field_path") in replaced_field_paths
            )
        ]
        new_fact_ids: list[str] = []
        for field_path in identity_fields:
            fact_id = _provider_fact_id(audit_id, candidate_id, field_path)
            new_fact_ids.append(fact_id)
            provider_field_path = (
                "name"
                if field_path == _PLACE_NAME_FIELD[candidate_kind]
                else field_path
            )
            source_locator_prefix = (
                "results"
                if cache_provenance is not None
                else "sanitized_result.results"
            )
            entity_ref = EntityRef(
                entity_type=_PLACE_ENTITY_TYPE[candidate_kind],
                entity_id=candidate_id,
            )
            facts.append(
                FactAssertion(
                    fact_assertion_id=fact_id,
                    entity_ref=entity_ref,
                    field_path=field_path,
                    asserted_value=provider_values[field_path],
                    criticality="decision_critical",
                    status="verified",
                    observed_at=observed_at,
                    source_links=[
                        FactSourceLink(
                            source_record_id=source_id,
                            relation="supports",
                            source_locator=(
                                f"{source_locator_prefix}[{result_index}].{provider_field_path}"
                            ),
                        )
                    ],
                ).model_dump(mode="python")
            )
            provenance.append(
                FieldProvenance(
                    origin="external_fact",
                    entity_ref=entity_ref,
                    field_path=field_path,
                    reference_ids=[fact_id],
                ).model_dump(mode="python")
            )
        if coordinate_pair is not None:
            coordinate_entity_ref = EntityRef(
                entity_type=_PLACE_ENTITY_TYPE[candidate_kind],
                entity_id=candidate_id,
            )
            coordinate_source_prefix = (
                "results"
                if cache_provenance is not None
                else "sanitized_result.results"
            )
            for coordinate_field, coordinate_value in (
                ("latitude", coordinate_pair[0]),
                ("longitude", coordinate_pair[1]),
            ):
                coordinate_fact_id = _provider_fact_id(
                    audit_id, candidate_id, coordinate_field
                )
                new_fact_ids.append(coordinate_fact_id)
                facts.append(
                    FactAssertion(
                        fact_assertion_id=coordinate_fact_id,
                        entity_ref=coordinate_entity_ref,
                        field_path=coordinate_field,
                        asserted_value=coordinate_value,
                        criticality="auxiliary",
                        status="verified",
                        observed_at=observed_at,
                        source_links=[
                            FactSourceLink(
                                source_record_id=source_id,
                                relation="supports",
                                source_locator=(
                                    f"{coordinate_source_prefix}[{result_index}].{coordinate_field}"
                                ),
                            )
                        ],
                    ).model_dump(mode="python")
                )
                provenance.append(
                    FieldProvenance(
                        origin="external_fact",
                        entity_ref=coordinate_entity_ref,
                        field_path=coordinate_field,
                        reference_ids=[coordinate_fact_id],
                    ).model_dump(mode="python")
                )
        replacement_id = new_fact_ids[0]
        evaluations = candidate.get("constraint_evaluations")
        if isinstance(evaluations, list):
            for evaluation in evaluations:
                if not isinstance(evaluation, dict):
                    continue
                references = evaluation.get("fact_assertion_ids")
                if isinstance(references, list) and replaced_fact_ids.intersection(
                    str(reference) for reference in references
                ):
                    evaluation["fact_assertion_ids"] = list(
                        dict.fromkeys(
                            replacement_id
                            if str(reference) in replaced_fact_ids
                            else reference
                            for reference in references
                        )
                    )
        retained_candidate_facts = [
            fact
            for fact in facts
            if isinstance(fact, dict)
            and (fact.get("entity_ref") or {}).get("entity_id") == candidate_id
            and fact.get("fact_assertion_id") not in new_fact_ids
        ]
        candidate["fact_assertion_ids"] = [
            *[
                str(fact["fact_assertion_id"])
                for fact in retained_candidate_facts
                if fact.get("fact_assertion_id")
            ],
            *new_fact_ids,
        ]
        candidate["source_record_ids"] = list(
            dict.fromkeys([*(candidate.get("source_record_ids") or []), source_id])
        )
        candidate["field_paths"] = list(
            dict.fromkeys(
                [
                    *[
                        str(fact["field_path"])
                        for fact in retained_candidate_facts
                        if fact.get("field_path")
                    ],
                    *identity_fields,
                ]
            )
        )
    if not bound_sources:
        return {}
    bound_audit_ids = {
        str(source.get("tool_audit_id") or source["snapshot"].get("audit_id") or "")
        for source in bound_sources.values()
    }
    sources = [
        source
        for source in sources
        if not (
            isinstance(source, dict)
            and (
                source.get("tool_audit_id") in bound_audit_ids
                or (
                    isinstance(source.get("snapshot"), dict)
                    and source["snapshot"].get("audit_id") in bound_audit_ids
                )
            )
        )
    ]
    if contradicted_places:
        # Provider 类型与候选种类不一致时只记录告警，不改写事实数据。
        logger.warning(
            "Research Packet provider record contradicts candidate kind | "
            "contradicted=%s",
            dict(contradicted_places),
        )
    payload["source_records"] = [*sources, *bound_sources.values()]
    payload["fact_assertions"] = facts
    payload["field_provenance"] = provenance
    return bound_sources


def _flight_endpoint_identity(endpoint: TransportEndpoint) -> tuple[str, str] | None:
    code = endpoint.station_code
    if (
        not isinstance(code, str)
        or len(code) != 3
        or not code.isascii()
        or not code.isalpha()
        or code != code.upper()
        or endpoint.place_id != f"iata:{code}"
    ):
        return None
    return endpoint.place_id, code


def _flight_segment_identity(segment: TransportSegment) -> tuple[Any, ...] | None:
    origin = _flight_endpoint_identity(segment.from_endpoint)
    destination = _flight_endpoint_identity(segment.to_endpoint)
    departure, arrival = segment.departure_at, segment.arrival_at
    if (
        segment.mode.value != "flight"
        or not segment.segment_id.strip()
        or origin is None
        or destination is None
        or departure is None
        or arrival is None
        or departure.utcoffset() is None
        or arrival.utcoffset() is None
    ):
        return None
    # 日期职责依照出发地本地日期，时区不能只按同一瞬时比较。
    return (
        segment.segment_id, origin, destination,
        (departure, departure.utcoffset()), (arrival, arrival.utcoffset()),
    )


def _matched_flight_segments(
    candidate: Mapping[str, Any],
    route: Mapping[str, Any],
    scopes: Sequence[ProviderEvidenceScope],
) -> list[TransportSegment] | None:
    """只为已选路线中身份与时刻均一致的航段接受号码。"""
    scope_id = candidate.get("provider_evidence_scope_id")
    matching_scopes = [
        scope for scope in scopes
        if scope.scope_id == scope_id
        and scope.worker_kind == "transport_researcher"
        and scope.transport_class == "long_distance"
        and scope.route_leg is not None
    ]
    if (
        (scope_id is not None and len(matching_scopes) != 1)
        or (scope_id is None and scopes)
        or candidate.get("transport_class") != "long_distance"
        or candidate.get("selected_mode") != "flight"
        or route.get("transport_class") != "long_distance"
        or route.get("selected_mode") != "flight"
        or not isinstance(candidate.get("route_id"), str)
        or candidate["route_id"] != route.get("route_id")
    ):
        return None
    candidate_segments = candidate.get("segments")
    provider_segments = route.get("segments")
    if (
        not isinstance(candidate_segments, list)
        or not isinstance(provider_segments, list)
        or not candidate_segments
        or len(candidate_segments) != len(provider_segments)
    ):
        return None
    try:
        selected = [TransportSegment.model_validate(item) for item in candidate_segments]
        supplied = [TransportSegment.model_validate(item) for item in provider_segments]
        selected_endpoints = [
            TransportEndpoint.model_validate(candidate.get(key))
            for key in ("from_endpoint", "to_endpoint")
        ]
        route_endpoints = [
            TransportEndpoint.model_validate(route.get(key))
            for key in ("from_endpoint", "to_endpoint")
        ]
    except (TypeError, ValueError, ValidationError):
        return None
    selected_ids = [_flight_segment_identity(item) for item in selected]
    supplied_ids = [_flight_segment_identity(item) for item in supplied]
    if (
        any(item is None for item in selected_ids + supplied_ids)
        or selected_ids != supplied_ids
        or len({item.segment_id for item in supplied}) != len(supplied)
    ):
        return None
    if any(item.arrival_at < item.departure_at for item in supplied) or any(
        supplied_ids[index][2] != supplied_ids[index + 1][1]
        or supplied[index].arrival_at > supplied[index + 1].departure_at
        for index in range(len(supplied) - 1)
    ):
        return None
    endpoint_ids = [_flight_endpoint_identity(item) for item in route_endpoints]
    if (
        None in endpoint_ids
        or [_flight_endpoint_identity(item) for item in selected_endpoints] != endpoint_ids
        or endpoint_ids != [supplied_ids[0][1], supplied_ids[-1][2]]
    ):
        return None
    departure, arrival = supplied[0].departure_at, supplied[-1].arrival_at
    for data in (candidate, route):
        try:
            times = [
                datetime.fromisoformat(str(data.get(key) or "").replace("Z", "+00:00"))
                for key in ("departure_at", "arrival_at")
            ]
        except ValueError:
            return None
        if times != [departure, arrival] or any(
            actual.utcoffset() != expected.utcoffset()
            for actual, expected in zip(times, (departure, arrival))
        ):
            return None
    if matching_scopes:
        leg = matching_scopes[0].route_leg
        assert leg is not None and departure is not None and arrival is not None
        # 城市范围的地点 ID 与机场 IATA 属于不同身份体系；不能据此推断城市归属。
        # 这里只核验所选航班的号码与日期，不创建或改写范围归属。
        if (
            (leg.from_place_id.startswith("iata:") and leg.from_place_id != endpoint_ids[0][0])
            or (leg.to_place_id.startswith("iata:") and leg.to_place_id != endpoint_ids[1][0])
            or leg.service_date != departure.date()
            or (leg.cross_day_required and arrival.date() == departure.date())
        ):
            return None
    return supplied


def _flight_segment_field(field_path: Any) -> bool:
    if not isinstance(field_path, str):
        return False
    return (
        field_path == "segments"
        or field_path.startswith(("segments.", "segments["))
        or field_path == "service_number"
    )


def _bind_successful_flight_numbers(
    payload: dict[str, Any],
    context_messages: Sequence[Mapping[str, Any]],
    *,
    scopes: Sequence[ProviderEvidenceScope],
    run_id: str,
) -> dict[str, SourceRecord]:
    """为模型已选的航班绑定可核验号码，清除无法证实的号码及其断言。"""
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return {}
    audits: dict[str, Mapping[str, Any]] = {}
    conflicting_audits: set[str] = set()
    for message in context_messages:
        envelope = message.get("content")
        if not isinstance(envelope, Mapping):
            continue
        audit_id = str(envelope.get("audit_id") or "").strip()
        if not audit_id:
            continue
        previous = audits.get(audit_id)
        if previous is not None and previous != envelope:
            conflicting_audits.add(audit_id)
        audits.setdefault(audit_id, envelope)
    flight_messages = [
        message for message in context_messages
        if isinstance(message.get("content"), Mapping)
        and message["content"].get("tool_name") == "search_flights"
        and message["content"].get("server_name") == "duffel-flights"
        and isinstance(message["content"].get("sanitized_result"), Mapping)
        and message["content"]["sanitized_result"].get("provider") == "duffel"
    ]
    records = _successful_route_records(flight_messages, reject_conflicting_ids=True)
    valid_scopes = [scope for scope in scopes if scope.run_id == run_id]
    if scopes and len(valid_scopes) != len(scopes):
        records = {}
    candidate_id_counts: dict[str, int] = {}
    for item in candidates:
        if isinstance(item, Mapping):
            item_id = str(item.get("candidate_id") or "").strip()
            candidate_id_counts[item_id] = candidate_id_counts.get(item_id, 0) + 1
    facts = payload.get("fact_assertions")
    facts = list(facts) if isinstance(facts, list) else []
    provenance = payload.get("field_provenance")
    provenance = list(provenance) if isinstance(provenance, list) else []
    sources = payload.get("source_records")
    sources = list(sources) if isinstance(sources, list) else []
    bound_sources: dict[str, SourceRecord] = {}
    removed_fact_ids: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict) or candidate.get("candidate_kind") != "transport":
            continue
        segments = candidate.get("segments")
        if not isinstance(segments, list):
            continue
        flight_segments = [
            segment for segment in segments
            if isinstance(segment, dict)
            and (segment.get("mode") == "flight" or candidate.get("selected_mode") == "flight")
        ]
        if not flight_segments:
            continue
        candidate_id = str(candidate.get("candidate_id") or "").strip()
        for segment in flight_segments:
            segment["service_number"] = None
        if not candidate_id:
            continue
        retained_facts = []
        for fact in facts:
            if (
                isinstance(fact, dict)
                and isinstance(fact.get("entity_ref"), Mapping)
                and fact["entity_ref"].get("entity_id") == candidate_id
                and _flight_segment_field(fact.get("field_path"))
            ):
                removed_fact_ids.add(str(fact.get("fact_assertion_id") or ""))
            else:
                retained_facts.append(fact)
        facts = retained_facts
        provenance = [
            item for item in provenance
            if not (
                isinstance(item, Mapping)
                and isinstance(item.get("entity_ref"), Mapping)
                and item["entity_ref"].get("entity_id") == candidate_id
                and _flight_segment_field(item.get("field_path"))
            )
        ]
        if candidate_id_counts[candidate_id] != 1:
            continue
        route_id = candidate.get("route_id")
        record = records.get(route_id) if isinstance(route_id, str) else None
        if record is None:
            continue
        envelope, route, route_index = record
        result = envelope.get("sanitized_result") or {}
        if (
            str(envelope.get("audit_id") or "").strip() in conflicting_audits
            or envelope.get("tool_name") != "search_flights"
            or envelope.get("server_name") != "duffel-flights"
            or result.get("provider") != "duffel"
            or route.get("provider") != "duffel"
            or not route_id.startswith("duffel:")
        ):
            continue
        supplied = _matched_flight_segments(candidate, route, valid_scopes)
        if supplied is None:
            continue
        numbered = [
            (index, segment.service_number)
            for index, segment in enumerate(supplied)
            if isinstance(segment.service_number, str)
            and re.fullmatch(r"[A-Z0-9]{2}[0-9]{1,4}[A-Z]?", segment.service_number)
        ]
        if not numbered:
            continue
        audit_id = str(envelope["audit_id"])
        new_fact_ids = {
            _provider_fact_id(audit_id, candidate_id, f"segments[{index}].service_number")
            for index, _ in numbered
        }
        if new_fact_ids & removed_fact_ids or any(
            isinstance(fact, Mapping) and fact.get("fact_assertion_id") in new_fact_ids
            for fact in facts
        ):
            continue
        source_id = _provider_route_source_id(audit_id, route_id)
        snapshot, cache, observed_at, retrieved_at, valid_until = _provider_snapshot_source_fields(
            envelope, fallback_observed_at=_payload_generated_at(payload)
        )
        bound_sources[source_id] = SourceRecord(
            source_record_id=source_id,
            source_kind="external_tool",
            title=f"duffel route: {route_id}",
            provider_name="duffel",
            public_excerpt=(
                f"{route['from_endpoint']['name']} → {route['to_endpoint']['name']}"
            )[:900],
            retrieved_at=retrieved_at,
            observed_at=observed_at,
            provider_valid_until=valid_until,
            content_hash=cache.content_hash if cache else _canonical_snapshot_hash(snapshot),
            snapshot=snapshot,
            tool_audit_id=audit_id,
            cache_provenance=cache,
        )
        entity_ref = EntityRef(entity_type=EntityType.TRANSPORT_LEG, entity_id=candidate_id)
        for index, number in numbered:
            segments[index]["service_number"] = number
            field_path = f"segments[{index}].service_number"
            fact_id = _provider_fact_id(audit_id, candidate_id, field_path)
            prefix = "" if cache is not None else "sanitized_result."
            facts.append(FactAssertion(
                fact_assertion_id=fact_id,
                entity_ref=entity_ref,
                field_path=field_path,
                asserted_value=number,
                criticality="execution_critical",
                status="verified",
                observed_at=observed_at,
                source_links=[FactSourceLink(
                    source_record_id=source_id,
                    relation="supports",
                    source_locator=f"{prefix}routes[{route_index}].{field_path}",
                )],
            ).model_dump(mode="python"))
            provenance.append(FieldProvenance(
                origin="external_fact",
                entity_ref=entity_ref,
                field_path=field_path,
                reference_ids=[fact_id],
            ).model_dump(mode="python"))
    payload["fact_assertions"] = facts
    payload["field_provenance"] = provenance
    _remove_fact_references(payload, removed_fact_ids)
    if bound_sources:
        payload["source_records"] = [
            source for source in sources
            if not isinstance(source, Mapping)
            or source.get("source_record_id") not in bound_sources
        ] + [source.model_dump(mode="python") for source in bound_sources.values()]
    return bound_sources
