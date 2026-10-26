from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Mapping, Sequence

from travel_agent.integrations.provider_environment import snapshot_data_environment
from travel_agent.knowledge.fragments import is_rag_chunk_source_id
from travel_agent.planning.research.evidence import (
    ProviderSnapshotProvenance,
    SourceRecord,
)

from .failures import _failed_tool_sources
from .identifiers import _canonical_snapshot_hash, _provider_entity_source_id
from .transcript import (
    _normalized_source_url,
    _retrieved_source_snapshots,
    _successful_place_records,
)

logger = logging.getLogger(__name__)

_SOURCE_CORE_FIELDS = frozenset(
    {"source_record_id", "title", "provider_name", "public_excerpt", "snapshot"}
)


def _sanitize_model_source_records(payload: dict[str, Any], *, default_retrieved_at) -> None:
    """规范化模型给出的来源记录：剔除未知字段，丢弃缺核心字段的条目并清理悬空链接。"""
    sources = payload.get("source_records")
    if not isinstance(sources, list):
        return
    allowed = set(SourceRecord.model_fields)
    kept: list[dict[str, Any]] = []
    dropped_ids: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("source_record_id") or source.get("id") or "")
        cleaned = {key: value for key, value in source.items() if key in allowed}
        if not _SOURCE_CORE_FIELDS.issubset(cleaned):
            dropped_ids.add(source_id)
            continue
        cleaned.setdefault("retrieved_at", default_retrieved_at)
        kept.append(cleaned)
    if dropped_ids:
        logger.warning("丢弃缺少核心字段的来源记录 %d 条", len(dropped_ids))
        for fact in payload.get("fact_assertions") or []:
            if isinstance(fact, dict) and isinstance(fact.get("source_links"), list):
                fact["source_links"] = [
                    link
                    for link in fact["source_links"]
                    if link.get("source_record_id") not in dropped_ids
                ]
        for candidate in payload.get("candidates") or []:
            if isinstance(candidate, dict) and isinstance(candidate.get("source_record_ids"), list):
                candidate["source_record_ids"] = [
                    source_id
                    for source_id in candidate["source_record_ids"]
                    if source_id not in dropped_ids
                ]
    payload["source_records"] = kept


def _drop_dangling_source_links(payload: dict[str, Any]) -> None:
    """丢弃指向 packet 外来源的链接，不让单个坏引用拖垮整个 packet。"""
    sources = payload.get("source_records") or []
    known_ids = {
        str(source.get("source_record_id"))
        for source in sources
        if isinstance(source, dict)
    }
    dropped = 0
    for fact in payload.get("fact_assertions") or []:
        if not isinstance(fact, dict) or not isinstance(fact.get("source_links"), list):
            continue
        before = len(fact["source_links"])
        fact["source_links"] = [
            link for link in fact["source_links"] if link.get("source_record_id") in known_ids
        ]
        dropped += before - len(fact["source_links"])
    for candidate in payload.get("candidates") or []:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("source_record_ids"), list):
            continue
        before = len(candidate["source_record_ids"])
        candidate["source_record_ids"] = [
            source_id for source_id in candidate["source_record_ids"] if source_id in known_ids
        ]
        dropped += before - len(candidate["source_record_ids"])
    if dropped:
        logger.warning("清理 packet 外来源的悬空链接 %d 条", dropped)


def _bind_source_content_hashes(
    payload: dict[str, Any],
    *,
    authoritative_sources: Mapping[str, SourceRecord | Mapping[str, Any]] | None = None,
) -> None:
    """规范化来源记录，不信任模型撰写的缓存来源信息。"""
    sources = payload.get("source_records")
    if not isinstance(sources, list):
        return
    canonical_sources: list[Any] = []
    for source in sources:
        if not isinstance(source, dict):
            canonical_sources.append(source)
            continue
        source_id = str(source.get("source_record_id") or "")
        authoritative = (authoritative_sources or {}).get(source_id)
        if authoritative is not None:
            canonical_sources.append(
                authoritative.model_dump(mode="python")
                if isinstance(authoritative, SourceRecord)
                else dict(authoritative)
            )
            continue
        # 注册表外的工具来源也按模型提供的记录保留，并同样重算内容哈希。
        snapshot = source.get("snapshot")
        if not isinstance(snapshot, dict):
            canonical_sources.append(source)
            continue
        source.pop("cache_provenance", None)
        source["content_hash"] = _canonical_snapshot_hash(snapshot)
        canonical_sources.append(source)
    payload["source_records"] = canonical_sources


_RETRIEVED_SOURCE_KINDS = frozenset({"external_web"})


def _ground_retrieved_sources_in_the_transcript(
    payload: dict[str, Any],
    evidence_messages: Sequence[Mapping[str, Any]],
    *,
    expected_worker: str,
) -> None:
    """只保留本轮确实检索到的页面，并绑定完整的 transcript 快照。"""
    sources = payload.get("source_records")
    if not isinstance(sources, list) or not sources:
        return
    snapshots = _retrieved_source_snapshots(evidence_messages)
    dropped: dict[str, str] = {}
    kept: list[Any] = []
    for source in sources:
        if (
            not isinstance(source, Mapping)
            or source.get("source_kind") not in _RETRIEVED_SOURCE_KINDS
        ):
            kept.append(source)
            continue
        source_id = str(source.get("source_record_id") or "")
        url = _normalized_source_url(source.get("canonical_url"))
        if url is None:
            dropped[source_id] = "no canonical_url"
        elif url not in snapshots:
            dropped[source_id] = f"url not retrieved this round: {url}"
        else:
            grounded = dict(source)
            grounded["snapshot"] = snapshots[url]
            kept.append(grounded)
    payload["source_records"] = kept
    if not dropped:
        return
    logger.warning(
        "Research Packet retrieved sources dropped (uncorroborated) | worker=%s "
        "retrieved_urls=%d dropped=%s",
        expected_worker,
        len(snapshots),
        dropped,
    )
    facts = payload.get("fact_assertions")
    if isinstance(facts, list):
        payload["fact_assertions"] = [
            fact
            for fact in facts
            if not (
                isinstance(fact, Mapping)
                and any(
                    isinstance(link, Mapping)
                    and str(link.get("source_record_id") or "") in dropped
                    for link in fact.get("source_links") or []
                )
            )
        ]


def _ground_rag_chunk_sources(
    payload: dict[str, Any],
    injected_rag_sources: Mapping[str, Mapping[str, Any]],
    *,
    expected_worker: str,
) -> None:
    """知识库引用只能落在已授权并展示给模型的工具片段上。"""
    facts = payload.get("fact_assertions")
    sources = payload.get("source_records")
    if not isinstance(sources, list):
        sources = []
    model_authored = {
        str(source.get("source_record_id") or "")
        for source in sources
        if isinstance(source, Mapping) and source.get("source_kind") == "rag_chunk"
    }
    kept = [
        source
        for source in sources
        if not (
            isinstance(source, Mapping) and source.get("source_kind") == "rag_chunk"
        )
    ]
    cited: set[str] = set()
    if isinstance(facts, list):
        for fact in facts:
            if not isinstance(fact, Mapping):
                continue
            for link in fact.get("source_links") or []:
                if not isinstance(link, Mapping):
                    continue
                source_id = str(link.get("source_record_id") or "")
                if is_rag_chunk_source_id(source_id) or source_id in model_authored:
                    cited.add(source_id)
    grounded = sorted(cited & set(injected_rag_sources))
    ungrounded = sorted(cited - set(injected_rag_sources))
    for source_id in grounded:
        kept.append(dict(injected_rag_sources[source_id]))
    payload["source_records"] = kept
    if not ungrounded:
        return
    logger.warning(
        "Research Packet rag_chunk sources dropped (not injected this round) | "
        "worker=%s injected=%d dropped=%s",
        expected_worker,
        len(injected_rag_sources),
        ungrounded,
    )
    if isinstance(facts, list):
        payload["fact_assertions"] = [
            fact
            for fact in facts
            if not (
                isinstance(fact, Mapping)
                and any(
                    isinstance(link, Mapping)
                    and str(link.get("source_record_id") or "") in ungrounded
                    for link in fact.get("source_links") or []
                )
            )
        ]


def _source_retrieved_at(envelope: Mapping[str, Any], fallback: Any) -> Any:
    raw = envelope.get("retrieved_at")
    if isinstance(raw, str) and raw.strip():
        try:
            return datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        except ValueError:
            pass
    return fallback


def _source_datetime(value: Any, fallback: Any) -> Any:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            pass
    return fallback


def _provider_snapshot_source_fields(
    envelope: Mapping[str, Any],
    *,
    fallback_observed_at: Any,
) -> tuple[
    dict[str, Any],
    ProviderSnapshotProvenance | None,
    Any,
    Any,
    Any,
]:
    """投影 Provider 的实际快照，而不是本次运行的工具信封。"""
    result = envelope.get("sanitized_result")
    metadata = envelope.get("metadata")
    cache_metadata = (
        metadata.get("snapshot_cache")
        if isinstance(metadata, Mapping)
        and isinstance(metadata.get("snapshot_cache"), Mapping)
        else None
    )
    if not isinstance(result, dict) or not isinstance(cache_metadata, Mapping):
        observed = _source_retrieved_at(envelope, fallback_observed_at)
        return dict(envelope), None, observed, observed, None
    origin = str(cache_metadata.get("origin") or "")
    provider_name = str(result.get("provider") or "").strip()
    tool_name = str(envelope.get("tool_name") or "").strip()
    if (
        origin not in {"live", "provider_snapshot_cache"}
        or not provider_name
        or not tool_name
    ):
        observed = _source_retrieved_at(envelope, fallback_observed_at)
        return dict(envelope), None, observed, observed, None
    observed_at = _source_datetime(
        cache_metadata.get("observed_at"),
        _source_retrieved_at(envelope, fallback_observed_at),
    )
    retrieved_at = _source_datetime(cache_metadata.get("retrieved_at"), observed_at)
    provider_valid_until = _source_datetime(cache_metadata.get("valid_until"), None)
    cache_valid_until = _source_datetime(cache_metadata.get("cache_valid_until"), None)
    try:
        provenance = ProviderSnapshotProvenance(
            origin=origin,
            data_environment=snapshot_data_environment(
                result, provider_name=provider_name
            ),
            provider_name=provider_name,
            tool_name=tool_name,
            cache_key_digest=str(cache_metadata.get("cache_key_digest") or ""),
            content_hash=str(cache_metadata.get("content_hash") or ""),
            observed_at=observed_at,
            retrieved_at=retrieved_at,
            provider_valid_until=provider_valid_until,
            cache_valid_until=cache_valid_until,
            provider_contract_version=str(cache_metadata.get("contract_version") or ""),
            payload_schema_version=str(
                cache_metadata.get("payload_schema_version") or ""
            ),
        )
    except (TypeError, ValueError):
        observed = _source_retrieved_at(envelope, fallback_observed_at)
        return dict(envelope), None, observed, observed, None
    return (
        dict(result),
        provenance,
        provenance.observed_at,
        provenance.retrieved_at,
        provenance.provider_valid_until,
    )


def _provider_place_source_payload(
    envelope: Mapping[str, Any],
    provider_place: Mapping[str, Any],
    *,
    fallback_observed_at: Any,
) -> dict[str, Any]:
    """为一次成功的 place 信封生成其唯一授权的来源记录。"""
    audit_id = str(envelope.get("audit_id") or "").strip()
    (
        snapshot,
        cache_provenance,
        observed_at,
        retrieved_at,
        provider_valid_until,
    ) = _provider_snapshot_source_fields(
        envelope,
        fallback_observed_at=fallback_observed_at,
    )
    provider_name = str(
        (envelope.get("sanitized_result") or {}).get("provider")
        or envelope.get("server_name")
        or "global_place_search"
    )
    return {
        "source_record_id": _provider_entity_source_id(
            audit_id,
            str(provider_place["place_id"]),
        ),
        "source_kind": "external_tool",
        "title": f"{provider_name} place record: {provider_place['name']}",
        "provider_name": provider_name,
        "public_excerpt": str(provider_place["address"])[:900],
        "retrieved_at": retrieved_at,
        "observed_at": observed_at,
        "provider_valid_until": provider_valid_until,
        "content_hash": (
            cache_provenance.content_hash
            if cache_provenance is not None
            else _canonical_snapshot_hash(snapshot)
        ),
        "snapshot": snapshot,
        "lifecycle_status": "active",
        "tool_audit_id": audit_id,
        "cache_provenance": (
            cache_provenance.model_dump(mode="json")
            if cache_provenance is not None
            else None
        ),
    }


def _authoritative_tool_source_records(
    evidence_messages: Sequence[Mapping[str, Any]],
    *,
    authoritative_source_records: Sequence[SourceRecord],
    default_retrieved_at: datetime,
) -> dict[str, SourceRecord]:
    """汇总服务端已持有的全部工具来源，供本 packet 使用。"""
    registry: dict[str, SourceRecord] = {
        source.source_record_id: source for source in authoritative_source_records
    }
    for place_id, (envelope, provider_place, _) in _successful_place_records(
        evidence_messages
    ).items():
        if not str(envelope.get("audit_id") or "").strip():
            continue
        payload = _provider_place_source_payload(
            envelope,
            provider_place,
            fallback_observed_at=default_retrieved_at,
        )
        registry.setdefault(
            str(payload["source_record_id"]),
            SourceRecord.model_validate(payload),
        )
    for source in _failed_tool_sources(
        existing_audit_ids=set(),
        context_messages=evidence_messages,
        default_retrieved_at=default_retrieved_at,
    ):
        registry.setdefault(source.source_record_id, source)
    return registry
