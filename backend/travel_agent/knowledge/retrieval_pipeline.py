"""One agent-selected query, cross-collection fusion, and at most one rerank."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ..config import get_settings
from .reranker import get_reranker
from .retriever import rrf_fuse


@dataclass(frozen=True)
class RetrievalOutcome:
    docs: List[Dict[str, Any]]
    query_variants: List[str] = field(default_factory=list)
    pool: List[Dict[str, Any]] = field(default_factory=list)
    reranked: bool = False
    failures: List[Dict[str, str]] = field(default_factory=list)


async def retrieve_for_query(
    query: str,
    *,
    retriever,
    collections: Sequence[str],
    top_k: int,
    use_rerank: bool = False,
    score_threshold: Optional[float] = None,
) -> RetrievalOutcome:
    settings = get_settings()
    if not settings.embedding.enabled:
        raise RuntimeError("向量知识库已由 embedding.enabled=false 关闭")
    probes = list(dict.fromkeys(collections))
    if not probes:
        return RetrievalOutcome(docs=[], query_variants=[query])
    raw_lists = await asyncio.gather(*[
        retriever.retrieve(
            query, collection=col, top_k=max(top_k, settings.rag.top_k),
            score_threshold=score_threshold, use_hybrid=True, rerank=False,
        )
        for col in probes
    ], return_exceptions=True)
    ranked_lists = []
    failures = []
    for col, raw in zip(probes, raw_lists):
        if isinstance(raw, Exception):
            failures.append({"collection": col, "scope": "collection", "error": type(raw).__name__})
            continue
        if isinstance(raw, BaseException):
            raise raw
        failures.extend({"collection": col, **failure} for failure in getattr(raw, "failures", []))
        ranked_lists.append([{**doc, "collection": col} for doc in raw or []])
    if not ranked_lists:
        raise RuntimeError("知识查询所有集合均检索失败")
    pool = rrf_fuse(ranked_lists, top_k=max(top_k, settings.rerank.initial_top_k))
    reranker = get_reranker() if use_rerank and pool else None
    if reranker is not None:
        docs = await reranker.rerank(query, pool, top_k=top_k)
    else:
        docs = pool[:top_k]
    return RetrievalOutcome(docs=docs, query_variants=[query], pool=pool,
                            reranked=reranker is not None, failures=failures)
