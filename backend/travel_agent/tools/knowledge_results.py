from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Sequence

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

