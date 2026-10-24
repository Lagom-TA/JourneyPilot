from __future__ import annotations

import hashlib
from typing import Any, Mapping

RAG_CHUNK_SOURCE_ID_PREFIX = "rag_"


_RAG_CHUNK_DIGEST_LENGTH = 16


def rag_chunk_source_id(doc: Mapping[str, Any]) -> str:
    "把一个 chunk 绑到一个 id：来源 + 正文的摘要。"

    material = f"{_source_name(doc)}\n{_content(doc)}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[
        :_RAG_CHUNK_DIGEST_LENGTH
    ]
    return f"{RAG_CHUNK_SOURCE_ID_PREFIX}{digest}"


def is_rag_chunk_source_id(source_record_id: str) -> bool:
    return str(source_record_id or "").startswith(RAG_CHUNK_SOURCE_ID_PREFIX)


def _content(doc: Mapping[str, Any]) -> str:
    return str(doc.get("original_content") or doc.get("content") or "").strip()


def _source_name(doc: Mapping[str, Any]) -> str:
    return str(doc.get("source") or "").strip() or "知识库文档"
