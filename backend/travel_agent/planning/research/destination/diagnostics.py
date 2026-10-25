"""Planning research destination diagnostics."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Sequence

from travel_agent.knowledge.collections import GroundingCorpus
from travel_agent.knowledge.place_mentions import (
    chunk_texts_by_collection,
    measure_place_funnel,
)
from travel_agent.planning.delivery.candidate_presentation import candidate_place_id
from travel_agent.planning.research.destination.scope import _NODE_NAME
from travel_agent.planning.research.output.options import observed_place_nominations
from travel_agent.planning.research.output.transcript import authoritative_tool_messages

logger = logging.getLogger(__name__)


def _log_rag_place_funnel(
    injected_rag_sources: Dict[str, Dict[str, Any]],
    *,
    authoritative_tool_results: List[Dict[str, Any]],
    candidates: Sequence[Any],
    corpus: GroundingCorpus,
) -> None:
    """Print how far this round's knowledge-base nominations got, per corpus."""

    by_collection = chunk_texts_by_collection(injected_rag_sources)
    user_texts = tuple(
        text
        for collection, texts in by_collection.items()
        if corpus.is_user_owned(collection)
        for text in texts
    )
    factory_texts = tuple(
        text
        for collection, texts in by_collection.items()
        if not corpus.is_user_owned(collection)
        for text in texts
    )
    rows: List[tuple[str, tuple[str, ...]]] = []
    if factory_texts:
        rows.append(("factory", factory_texts))
    rows.append(("user", user_texts))

    observed = observed_place_nominations(
        authoritative_tool_messages(authoritative_tool_results),
        expected_worker=_NODE_NAME,
    )
    admitted_place_ids = [
        place_id
        for candidate in candidates
        if (place_id := candidate_place_id(candidate))
    ]
    for origin, texts in rows:
        funnel = measure_place_funnel(
            injected_chunk_texts=texts,
            lookups=observed.lookups,
            selectable_place_ids=observed.selectable_place_ids,
            admitted_place_ids=admitted_place_ids,
        )
        logger.info("RAG place funnel [origin=%s]: %s", origin, funnel.as_log_line())
