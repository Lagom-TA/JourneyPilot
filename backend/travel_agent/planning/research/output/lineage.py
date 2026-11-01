from __future__ import annotations

import logging
from typing import Any, Mapping

from travel_agent.tools.governance import (
    COMPILED_TOOL_SOURCE_ID_PREFIX,
    compiled_tool_source_id_is_about,
)


logger = logging.getLogger(__name__)


def _prune_payload_to_candidate_closure(payload: dict[str, Any]) -> None:
    """只保留可从当前候选到达的事实、来源与来源标注。"""
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
    available_source_ids = {
        str(source.get("source_record_id") or "")
        for source in sources
        if isinstance(source, Mapping) and source.get("source_record_id")
    }
    # 先清理指向 packet 外来源的链接，再按剩余链接保留来源。
    for fact in retained_facts:
        if not isinstance(fact.get("source_links"), list):
            continue
        fact["source_links"] = [
            link
            for link in fact["source_links"]
            if str(link.get("source_record_id") or "") in available_source_ids
        ]
    retained_source_ids = {
        str(link.get("source_record_id") or "")
        for fact in retained_facts
        for link in fact.get("source_links") or []
        if isinstance(link, Mapping) and link.get("source_record_id")
    }
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
    """候选 id 到其编译来源所用实体 id 的映射。"""
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
    """拒绝为其他实体编译的来源链接。"""
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
