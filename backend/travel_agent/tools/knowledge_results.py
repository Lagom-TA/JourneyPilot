from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Sequence

from ..knowledge.summary import build_retrieval_summary
from .content import compact_tool_content_for_model
from .governance import is_tool_execution_envelope


def knowledge_tool_documents(
    envelopes: Sequence[Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    documents: Dict[str, Dict[str, Any]] = {}
    for envelope in envelopes:
        if (
            not is_tool_execution_envelope(envelope)
            or envelope.get("tool_name") != "knowledge_search"
        ):
            continue
        if envelope.get("status") != "success":
            continue
        metadata = envelope.get("metadata") or {}
        if metadata.get("evidence_allowed") is not True or metadata.get(
            "quarantine_result"
        ):
            continue
        # 引用只能指向模型可见 JSON 中保留的完整片段。
        shown = json.loads(compact_tool_content_for_model(dict(envelope)))
        result = shown.get("sanitized_result") or {}
        if not isinstance(result, dict) or result.get("success") is not True:
            continue
        for doc in result.get("documents") or []:
            if (
                isinstance(doc, dict)
                and doc.get("content")
                and doc.get("source_record_id")
            ):
                documents[doc["source_record_id"]] = doc
    return list(documents.values())


def knowledge_tool_summaries(
    envelopes: Sequence[Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    summaries = []
    for envelope in envelopes:
        if envelope.get("tool_name") != "knowledge_search":
            continue
        docs = knowledge_tool_documents([envelope])
        result = envelope.get("sanitized_result") or {}
        if not isinstance(result, dict):
            result = {}
        summary = build_retrieval_summary(
            str(result.get("query") or ""),
            docs,
            collections=result.get("collections") or [],
            mode_decision={
                "retrieval_mode": "agentic_knowledge_search",
                "enabled_features": ["hybrid", "rrf"],
            },
        ).to_dict()
        summary["status"] = result.get("retrieval_status") or envelope.get("status")
        summary["failures"] = result.get("failures") or []
        summary["audit_id"] = envelope.get("audit_id")
        summaries.append(summary)
    return summaries
