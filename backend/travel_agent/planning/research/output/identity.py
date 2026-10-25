"""Research packet identity responsibilities."""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping, Sequence

from travel_agent.planning.references import EntityRef, EntityType
from travel_agent.planning.research.evidence import (
    FactAssertion,
    FactSourceLink,
    FieldProvenance,
)
from travel_agent.services.candidate_admission import (
    provider_place_type_matches_candidate_kind,
)
from travel_agent.tools.governance import compiled_tool_source_id_is_about

from .identifiers import (
    _canonical_snapshot_hash,
    _provider_entity_source_id,
    _provider_fact_id,
)
from .policy import _PLACE_ENTITY_TYPE, _PLACE_IDENTITY_FIELDS, _PLACE_NAME_FIELD
from .sources import (
    _provider_place_source_payload,
    _provider_snapshot_source_fields,
    _source_retrieved_at,
)
from .transcript import _quality_verified_place_sources, _successful_place_records

logger = logging.getLogger(__name__)


def _provider_coordinate_pair(
    provider_place: Mapping[str, Any],
) -> tuple[float, float] | None:
    "Extract a valid (latitude, longitude) pair from a provider place record."
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
    "Bind Provider identity to a Worker-selected place without selecting it."
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return {}
    records = _successful_place_records(context_messages)
    quality_sources = _quality_verified_place_sources(context_messages)
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
        if candidate_kind == "dining":
            replaced_field_paths.add("external_quality_match")
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
        if candidate_kind == "dining":
            quality_envelopes = quality_sources.get(place_id, [])
            quality_source_links: list[FactSourceLink] = []
            quality_audit_ids: list[str] = []
            for quality_envelope in quality_envelopes:
                quality_audit_id = str(quality_envelope.get("audit_id") or "").strip()
                if not quality_audit_id:
                    continue
                quality_audit_ids.append(quality_audit_id)
                quality_source_id = _provider_entity_source_id(
                    quality_audit_id,
                    place_id,
                )
                quality_observed_at = _source_retrieved_at(
                    quality_envelope,
                    generated_at,
                )
                quality_snapshot = dict(quality_envelope)
                quality_provider_name = str(
                    quality_envelope.get("server_name")
                    or quality_envelope.get("tool_name")
                    or "external_review_search"
                )
                quality_result = quality_envelope.get("sanitized_result") or {}
                bound_sources[quality_source_id] = {
                    "source_record_id": quality_source_id,
                    "source_kind": "external_tool",
                    "title": (
                        f"{quality_provider_name} branch review match: "
                        f"{provider_place['name']}"
                    ),
                    "provider_name": quality_provider_name,
                    "public_excerpt": json.dumps(
                        quality_result,
                        ensure_ascii=False,
                        default=str,
                    )[:900],
                    "retrieved_at": quality_observed_at,
                    "observed_at": quality_observed_at,
                    "content_hash": _canonical_snapshot_hash(quality_snapshot),
                    "snapshot": quality_snapshot,
                    "lifecycle_status": "active",
                }
                quality_source_links.append(
                    FactSourceLink(
                        source_record_id=quality_source_id,
                        relation="supports",
                        source_locator="sanitized_result",
                    )
                )
            if quality_source_links:
                quality_fact_id = _provider_fact_id(
                    "+".join(quality_audit_ids),
                    candidate_id,
                    "external_quality_match",
                )
                facts.append(
                    FactAssertion(
                        fact_assertion_id=quality_fact_id,
                        entity_ref=EntityRef(
                            entity_type=EntityType.DINING_STOP,
                            entity_id=candidate_id,
                        ),
                        field_path="external_quality_match",
                        asserted_value=True,
                        criticality="decision_critical",
                        status="verified",
                        observed_at=observed_at,
                        source_links=quality_source_links,
                    ).model_dump(mode="python")
                )
                provenance.append(
                    FieldProvenance(
                        origin="external_fact",
                        entity_ref=EntityRef(
                            entity_type=EntityType.DINING_STOP,
                            entity_id=candidate_id,
                        ),
                        field_path="external_quality_match",
                        reference_ids=[quality_fact_id],
                    ).model_dump(mode="python")
                )
                new_fact_ids.append(quality_fact_id)
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
        facts = _without_contradicted_place_support(facts, contradicted_places)
    payload["source_records"] = [*sources, *bound_sources.values()]
    payload["fact_assertions"] = facts
    payload["field_provenance"] = provenance
    return bound_sources


def _without_contradicted_place_support(
    facts: list[Any],
    contradicted_places: Mapping[str, str],
) -> list[Any]:
    "Strip compiled support the Provider's own record argues against."
    kept: list[Any] = []
    dropped: dict[str, str] = {}
    for fact in facts:
        if not isinstance(fact, dict):
            kept.append(fact)
            continue
        entity_id = str((fact.get("entity_ref") or {}).get("entity_id") or "")
        place_id = contradicted_places.get(entity_id)
        links = fact.get("source_links")
        if place_id is None or not isinstance(links, list):
            kept.append(fact)
            continue
        kept_links = [
            link
            for link in links
            if not (
                isinstance(link, Mapping)
                and compiled_tool_source_id_is_about(
                    str(link.get("source_record_id") or ""), place_id
                )
            )
        ]
        if len(kept_links) == len(links):
            kept.append(fact)
            continue
        dropped[str(fact.get("fact_assertion_id") or "")] = place_id
        if kept_links:
            kept.append({**fact, "source_links": kept_links})
    if dropped:
        logger.warning(
            "Research Packet compiled place support dropped (provider contradicts "
            "candidate kind) | contradicted=%s facts=%s",
            dict(contradicted_places),
            dropped,
        )
    return kept
