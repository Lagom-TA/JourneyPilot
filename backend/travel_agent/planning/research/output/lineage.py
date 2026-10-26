"""Research packet lineage responsibilities."""

from __future__ import annotations

import logging
import re
from typing import Any, Mapping

from travel_agent.tools.governance import (
    COMPILED_TOOL_SOURCE_ID_PREFIX,
    compiled_tool_source_id_is_about,
)

from .policy import ResearchPacketOutputError

logger = logging.getLogger(__name__)


def _prune_payload_to_candidate_closure(payload: dict[str, Any]) -> None:
    "Keep only facts, sources, and provenance reachable from current candidates."
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return
    candidate_ids = {
        str(candidate.get("candidate_id") or "")
        for candidate in candidates
        if isinstance(candidate, Mapping) and candidate.get("candidate_id")
    }
    facts = payload.get("fact_assertions")
    sources = payload.get("source_records")
    provenance = payload.get("field_provenance")
    if (
        not isinstance(facts, list)
        or not isinstance(sources, list)
        or not isinstance(provenance, list)
    ):
        return
    retained_facts = [
        fact
        for fact in facts
        if isinstance(fact, Mapping)
        and str((fact.get("entity_ref") or {}).get("entity_id") or "") in candidate_ids
    ]
    retained_fact_ids = {
        str(fact.get("fact_assertion_id") or "")
        for fact in retained_facts
        if fact.get("fact_assertion_id")
    }
    retained_source_ids = {
        str(link.get("source_record_id") or "")
        for fact in retained_facts
        for link in fact.get("source_links") or []
        if isinstance(link, Mapping) and link.get("source_record_id")
    }
    available_source_ids = {
        str(source.get("source_record_id") or "")
        for source in sources
        if isinstance(source, Mapping) and source.get("source_record_id")
    }
    if not retained_source_ids <= available_source_ids:
        raise ResearchPacketOutputError(
            "research packet fact references a source outside the packet"
        )
    retained_sources = [
        source
        for source in sources
        if isinstance(source, Mapping)
        and (
            str(source.get("source_record_id") or "") in retained_source_ids
            or source.get("lifecycle_status") == "rejected"
        )
    ]
    retained_provenance: list[Any] = []
    for item in provenance:
        if (
            not isinstance(item, Mapping)
            or str((item.get("entity_ref") or {}).get("entity_id") or "")
            not in candidate_ids
        ):
            continue
        copied = dict(item)
        if copied.get("origin") == "external_fact":
            references = [
                reference_id
                for reference_id in copied.get("reference_ids") or []
                if str(reference_id) in retained_fact_ids
            ]
            if not references:
                continue
            copied["reference_ids"] = references
        retained_provenance.append(copied)
    payload["fact_assertions"] = retained_facts
    payload["source_records"] = retained_sources
    payload["field_provenance"] = retained_provenance


def _candidate_provenance_entity_ids(payload: Mapping[str, Any]) -> dict[str, str]:
    "Each candidate id mapped to the entity its compiled sources are minted under."
    entity_ids: dict[str, str] = {}
    for candidate in payload.get("candidates") or []:
        if not isinstance(candidate, Mapping):
            continue
        candidate_id = str(candidate.get("candidate_id") or "").strip()
        key = (
            "route_id"
            if str(candidate.get("candidate_kind") or "") == "transport"
            else "place_id"
        )
        entity_id = str(candidate.get(key) or "").strip()
        if candidate_id and entity_id:
            entity_ids[candidate_id] = entity_id
    return entity_ids


def _drop_borrowed_compiled_source_links(
    payload: dict[str, Any],
    *,
    expected_worker: str,
) -> None:
    "Refuse a compiled source that was minted for some *other* entity."
    facts = payload.get("fact_assertions")
    if not isinstance(facts, list) or not facts:
        return
    entity_ids = _candidate_provenance_entity_ids(payload)
    if not entity_ids:
        return
    dropped_links: dict[str, str] = {}
    dropped_facts: list[str] = []
    kept_facts: list[Any] = []
    for fact in facts:
        if not isinstance(fact, Mapping):
            kept_facts.append(fact)
            continue
        entity_ref = fact.get("entity_ref")
        owner = (
            str(entity_ref.get("entity_id") or "").strip()
            if isinstance(entity_ref, Mapping)
            else ""
        )
        entity_id = entity_ids.get(owner)
        links = fact.get("source_links")
        if entity_id is None or not isinstance(links, list):
            kept_facts.append(fact)
            continue
        kept_links = []
        for link in links:
            source_id = (
                str(link.get("source_record_id") or "")
                if isinstance(link, Mapping)
                else ""
            )
            if source_id.startswith(
                COMPILED_TOOL_SOURCE_ID_PREFIX
            ) and not compiled_tool_source_id_is_about(source_id, entity_id):
                dropped_links[str(fact.get("fact_assertion_id") or "")] = source_id
                continue
            kept_links.append(link)
        if not kept_links:
            dropped_facts.append(str(fact.get("fact_assertion_id") or ""))
            continue
        kept_facts.append({**fact, "source_links": kept_links})
    if not dropped_links:
        return
    logger.warning(
        "Research Packet compiled source links dropped (wrong entity) | worker=%s "
        "dropped_links=%s dropped_facts=%s",
        expected_worker,
        dropped_links,
        dropped_facts or "-",
    )
    payload["fact_assertions"] = kept_facts


def _normalized_semantic_key(value: Any) -> str:
    "Normalize an already-structured semantic label for exact fallback joins."
    return re.sub(r"[^\w]+", "", str(value or "").casefold(), flags=re.UNICODE)


def _query_row_matches_provider_identity(
    row: Mapping[str, Any],
    *,
    provider_query: str,
    candidate_name: str,
) -> bool:
    "Join Provider identity to an LLM-authored query without new NLP rules."
    provider_key = _normalized_semantic_key(provider_query)
    name_key = _normalized_semantic_key(candidate_name)
    query_key = _normalized_semantic_key(row.get("query_text"))
    if provider_key and query_key and provider_key == query_key:
        return True
    aliases = [
        _normalized_semantic_key(alias)
        for alias in row.get("aliases") or []
        if _normalized_semantic_key(alias)
    ]
    return any(
        alias == name_key
        or (provider_key and alias in provider_key)
        or (name_key and alias in name_key)
        for alias in aliases
    )


def _bind_candidate_discovery_lineage(payload: dict[str, Any]) -> None:
    """Bind every candidate to the executed-query lineage observable server-side."""
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return
    query_context = payload.get("query_context")
    query_rows = (
        query_context.get("query_lineage") if isinstance(query_context, Mapping) else []
    )
    query_rows = [row for row in (query_rows or []) if isinstance(row, Mapping)]
    executed_ids = {
        str(query_id)
        for query_id in payload.get("executed_query_ids") or []
        if str(query_id)
    }
    origin_by_kind = {
        "intent_primary": "intent_query",
        "structural": "structural_query",
        "evidence_enrichment": "structural_query",
        "generic_fallback": "generic_fallback",
        "targeted_repair": "targeted_repair",
    }
    source_by_id = {
        str(source.get("source_record_id") or ""): source
        for source in payload.get("source_records") or []
        if isinstance(source, Mapping)
    }
    research_round = 0
    if isinstance(query_context, Mapping):
        try:
            research_round = max(int(query_context.get("research_round") or 0), 0)
        except (TypeError, ValueError):
            research_round = 0
    records = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        candidate_kind = str(candidate.get("candidate_kind") or "")
        domain_values = (
            {"visit"}
            if candidate_kind == "visit"
            else {"dining"}
            if candidate_kind == "dining"
            else {"lodging"}
            if candidate_kind == "lodging"
            else {
                "long_distance_transport"
                if candidate.get("transport_class") == "long_distance"
                else "local_transport"
            }
        )
        domain_rows = [
            row
            for row in query_rows
            if str(row.get("query_id") or "") in executed_ids
            and str(row.get("domain") or "") in domain_values
        ]
        provider_queries: list[str] = []
        for source_id in candidate.get("source_record_ids") or []:
            source = source_by_id.get(str(source_id))
            snapshot = source.get("snapshot") if isinstance(source, Mapping) else None
            query = snapshot.get("query") if isinstance(snapshot, Mapping) else None
            if isinstance(query, str) and query.strip():
                provider_queries.append(query.strip())
        candidate_name = str(
            candidate.get("name")
            or candidate.get("property_name")
            or candidate.get("route_id")
            or ""
        )
        traced_rows = [
            row
            for row in domain_rows
            if any(
                _query_row_matches_provider_identity(
                    row,
                    provider_query=provider_query,
                    candidate_name=candidate_name,
                )
                for provider_query in provider_queries
            )
        ]
        if provider_queries and candidate_kind in {"visit", "dining"}:
            relevant = traced_rows or [
                row
                for row in domain_rows
                if str(row.get("query_kind") or "")
                not in {"intent_primary", "targeted_repair"}
            ]
        else:
            relevant = domain_rows
        query_ids = list(dict.fromkeys(str(row["query_id"]) for row in relevant))
        intent_ids = list(
            dict.fromkeys(
                str(intent_id)
                for row in relevant
                for intent_id in row.get("intent_ids") or []
                if str(intent_id)
            )
        )
        origins = list(
            dict.fromkeys(
                origin_by_kind.get(str(row.get("query_kind") or ""), "structural_query")
                for row in relevant
            )
        )
        candidate_id = str(candidate.get("candidate_id") or "")
        provider_audit_ids = list(
            dict.fromkeys(
                str(source.get("tool_audit_id") or "")
                for source_id in candidate.get("source_record_ids") or []
                if (source := source_by_id.get(str(source_id))) is not None
                and source.get("tool_audit_id")
            )
        )
        records.append(
            {
                "candidate_id": candidate_id,
                "generation_id": str(payload.get("generation_id") or ""),
                "query_ids": query_ids,
                "intent_ids": intent_ids,
                "origins": origins,
                "provider_audit_ids": provider_audit_ids,
                "discovered_at_rounds": [research_round],
            }
        )
    payload["candidate_discovery_records"] = records
