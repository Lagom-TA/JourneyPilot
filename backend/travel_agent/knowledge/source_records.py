"""Server-owned citations for the exact knowledge fragments shown by tool calls."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Sequence
from urllib.parse import urlsplit

from .fragments import _content, _source_name, rag_chunk_source_id

_PUBLIC_EXCERPT_LIMIT = 400


def rag_chunk_source_records(
    docs: Sequence[Mapping[str, Any]],
    *,
    default_retrieved_at: Optional[datetime] = None,
) -> Dict[str, Dict[str, Any]]:
    """Build citations from the exact fragments retained in model-facing tool receipts."""

    records: Dict[str, Dict[str, Any]] = {}
    for doc in docs:
        if not isinstance(doc, Mapping):
            continue
        content = _content(doc)
        if not content:
            continue
        source_id = rag_chunk_source_id(doc)
        if source_id in records:
            continue
        records[source_id] = _source_payload(
            doc,
            source_id=source_id,
            content=content,
            default_retrieved_at=default_retrieved_at,
        )
    return records


def _source_payload(
    doc: Mapping[str, Any],
    *,
    source_id: str,
    content: str,
    default_retrieved_at: Optional[datetime],
) -> Dict[str, Any]:
    snapshot = _snapshot(doc, content)
    return {
        "source_record_id": source_id,
        "source_kind": "rag_chunk",
        "title": _source_name(doc),
        "provider_name": _provider_name(doc),
        "attestation": "external",
        "canonical_url": _canonical_url(doc),
        "public_excerpt": content[:_PUBLIC_EXCERPT_LIMIT],
        "published_at": _parse_datetime(doc.get("published_at")),
        "retrieved_at": _parse_datetime(doc.get("retrieved_at"))
        or default_retrieved_at
        or datetime.now(timezone.utc),
        "content_hash": _canonical_snapshot_hash(snapshot),
        "snapshot": snapshot,
        "lifecycle_status": "active",
    }


def _snapshot(doc: Mapping[str, Any], content: str) -> Dict[str, Any]:
    """完整的 chunk，不是摘要。

    合同原话是「完整工具返回或完整 RAG chunk，禁止裁剪成模型摘要」，而下游
    `services/delivery_projection.py::_public_source` 的 `rag_chunk` 分支在 chunk
    内容缺失时会抛错——它等的就是这里的 ``content``。
    """

    snapshot: Dict[str, Any] = {
        "collection": str(doc.get("collection") or ""),
        "source": _source_name(doc),
        "content": content,
        "retrieval_method": str(doc.get("retrieval_method") or ""),
    }
    metadata = doc.get("metadata")
    if isinstance(metadata, Mapping) and metadata:
        snapshot["metadata"] = dict(metadata)
    scores = {
        key: doc[key]
        for key in ("vector_score", "lexical_score", "fusion_score", "rerank_score")
        if doc.get(key) is not None
    }
    if scores:
        snapshot["retrieval_scores"] = scores
    return snapshot


def _canonical_snapshot_hash(snapshot: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def _provider_name(doc: Mapping[str, Any]) -> str:
    collection = str(doc.get("collection") or "").strip()
    return f"knowledge_base:{collection}" if collection else "knowledge_base"


def _canonical_url(doc: Mapping[str, Any]) -> Optional[str]:
    """来源是网址就带上；是文件名就留空。

    ``canonical_url`` 在 ``SourceRecord`` 上本来就是可选的，往里塞一个不是 URL 的
    文件名，只会让下游把它当链接渲染。
    """

    candidate = str(doc.get("source") or "").strip()
    if not candidate:
        return None
    parsed = urlsplit(candidate)
    return candidate if parsed.scheme and parsed.netloc else None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


__all__ = ["rag_chunk_source_records"]
