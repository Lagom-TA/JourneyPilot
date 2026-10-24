"""Server-owned citations for the exact knowledge fragments shown by tool calls."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Sequence
from urllib.parse import urlsplit

RAG_CHUNK_SOURCE_ID_PREFIX = "rag_"
_RAG_CHUNK_DIGEST_LENGTH = 16
_PUBLIC_EXCERPT_LIMIT = 400


def knowledge_tool_documents(envelopes: Sequence[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    from ..agents.utils import compact_tool_content_for_model
    from ..tools.governance import is_tool_execution_envelope

    documents: Dict[str, Dict[str, Any]] = {}
    for envelope in envelopes:
        if not is_tool_execution_envelope(envelope) or envelope.get("tool_name") != "knowledge_search":
            continue
        if envelope.get("status") != "success":
            continue
        metadata = envelope.get("metadata") or {}
        if metadata.get("evidence_allowed") is not True or metadata.get("quarantine_result"):
            continue
        shown = json.loads(compact_tool_content_for_model(dict(envelope)))
        result = shown.get("sanitized_result") or {}
        if not isinstance(result, dict) or result.get("success") is not True:
            continue
        for doc in result.get("documents") or []:
            if isinstance(doc, dict) and doc.get("content") and doc.get("source_record_id"):
                documents[doc["source_record_id"]] = doc
    return list(documents.values())


def knowledge_tool_summaries(envelopes: Sequence[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    from .summary import build_retrieval_summary

    summaries = []
    for envelope in envelopes:
        if envelope.get("tool_name") != "knowledge_search":
            continue
        docs = knowledge_tool_documents([envelope])
        result = envelope.get("sanitized_result") or {}
        if not isinstance(result, dict):
            result = {}
        summary = build_retrieval_summary(
            str(result.get("query") or ""), docs,
            collections=result.get("collections") or [],
            mode_decision={"retrieval_mode": "agentic_knowledge_search", "enabled_features": ["hybrid", "rrf"]},
        ).to_dict()
        summary["status"] = result.get("retrieval_status") or envelope.get("status")
        summary["failures"] = result.get("failures") or []
        summary["audit_id"] = envelope.get("audit_id")
        summaries.append(summary)
    return summaries


def rag_chunk_source_id(doc: Mapping[str, Any]) -> str:
    """把一个 chunk 绑到一个 id：来源 + 正文的摘要。

    同一段正文在同一个来源下永远得到同一个 id，所以一轮里重复命中的 chunk 只会
    产生一条源记录，跨重试轮也稳定。
    """

    material = f"{_source_name(doc)}\n{_content(doc)}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[
        :_RAG_CHUNK_DIGEST_LENGTH
    ]
    return f"{RAG_CHUNK_SOURCE_ID_PREFIX}{digest}"


def is_rag_chunk_source_id(source_record_id: str) -> bool:
    return str(source_record_id or "").startswith(RAG_CHUNK_SOURCE_ID_PREFIX)


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


def _content(doc: Mapping[str, Any]) -> str:
    return str(doc.get("original_content") or doc.get("content") or "").strip()


def _source_name(doc: Mapping[str, Any]) -> str:
    return str(doc.get("source") or "").strip() or "知识库文档"


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


__all__ = [
    "RAG_CHUNK_SOURCE_ID_PREFIX",
    "is_rag_chunk_source_id",
    "rag_chunk_source_id",
    "rag_chunk_source_records",
]
