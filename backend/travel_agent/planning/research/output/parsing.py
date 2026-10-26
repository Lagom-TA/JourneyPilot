"""Research packet parsing responsibilities."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Mapping, Optional, Sequence

from pydantic import ValidationError

from travel_agent.knowledge.source_records import rag_chunk_source_records
from travel_agent.planning.research.evidence import SourceRecord
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.tools.knowledge_results import knowledge_tool_documents

from .identity import _bind_successful_place_identity
from .lineage import (
    _bind_candidate_discovery_lineage,
    _drop_borrowed_compiled_source_links,
    _prune_payload_to_candidate_closure,
)
from .metadata import (
    _bind_authoritative_candidate_constraints,
    _bind_authoritative_packet_metadata,
    _payload_generated_at,
)
from .policy import ResearchPacketOutputError, ResearchWorkerKind
from .sources import (
    _authoritative_tool_source_records,
    _bind_source_content_hashes,
    _ground_rag_chunk_sources,
    _ground_retrieved_sources_in_the_transcript,
)
from .transcript import authoritative_tool_messages

logger = logging.getLogger(__name__)


def _isolate_json_object(text: str) -> Optional[dict]:
    """Parse the outermost balanced JSON object without inventing content."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start : i + 1])
                    if isinstance(obj, dict):
                        return obj
                except (TypeError, json.JSONDecodeError):
                    continue
    return None


def _coerce_exact_json_object(raw: str) -> Optional[dict]:
    """Extract the model's JSON object from fences or surrounding prose."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    obj = None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except (TypeError, json.JSONDecodeError):
        pass
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    candidate = fence.group(1).strip() if fence else raw
    obj = _isolate_json_object(candidate)
    if obj is not None:
        return obj
    return None


def parse_research_packet_output(
    raw: str,
    *,
    expected_worker: ResearchWorkerKind,
    expected_run_id: str,
    expected_active_constraint_ids: Sequence[str] | None = None,
    authoritative_tool_results: Sequence[Mapping[str, Any]] = (),
    authoritative_packet_metadata: Mapping[str, Any] | None = None,
    authoritative_source_records: Sequence[SourceRecord] = (),
) -> ResearchPacket:
    "Parse exact JSON only; no Markdown extraction, repair, or envelope fallback."
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ResearchPacketOutputError("worker output must be one JSON object")
    except (TypeError, json.JSONDecodeError) as exc:
        raise ResearchPacketOutputError(
            "worker output is not an exact JSON object"
        ) from exc
    _bind_authoritative_packet_metadata(payload, authoritative_packet_metadata)
    _bind_authoritative_candidate_constraints(
        payload,
        expected_active_constraint_ids,
    )
    evidence_messages = authoritative_tool_messages(authoritative_tool_results)
    compiled_tool_sources = _authoritative_tool_source_records(
        evidence_messages,
        authoritative_source_records=authoritative_source_records,
        default_retrieved_at=_payload_generated_at(payload),
    )
    authoritative_sources: dict[str, SourceRecord | Mapping[str, Any]] = dict(
        compiled_tool_sources
    )
    authoritative_sources.update(
        _bind_successful_place_identity(payload, evidence_messages)
    )
    _ground_retrieved_sources_in_the_transcript(
        payload, evidence_messages, expected_worker=expected_worker
    )
    rag_sources = rag_chunk_source_records(
        knowledge_tool_documents(authoritative_tool_results)
    )
    _ground_rag_chunk_sources(payload, rag_sources, expected_worker=expected_worker)
    authoritative_sources.update(rag_sources)
    # Bind real identity first so corrected links are not rejected as borrowed.
    _drop_borrowed_compiled_source_links(payload, expected_worker=expected_worker)
    _prune_payload_to_candidate_closure(payload)
    _bind_source_content_hashes(
        payload,
        authoritative_sources=authoritative_sources,
    )
    if not payload.get("source_records"):
        payload["source_records"] = [
            source.model_dump(mode="python")
            for source in compiled_tool_sources.values()
        ]
    _bind_candidate_discovery_lineage(payload)
    try:
        packet = ResearchPacket.model_validate(payload)
    except ValidationError as exc:
        raise ResearchPacketOutputError(
            f"worker Research Packet failed structural validation: {exc}"
        ) from exc
    if packet.worker_kind != expected_worker:
        raise ResearchPacketOutputError(
            "worker Research Packet domain does not match the node"
        )
    if packet.run_id != expected_run_id:
        raise ResearchPacketOutputError(
            "worker Research Packet run id does not match active run"
        )
    return packet


def _parse_packet_lenient_first(raw: str, **kwargs: Any) -> ResearchPacket:
    "Initial worker-packet parse: tolerate Markdown fences / surrounding prose."
    try:
        return parse_research_packet_output(raw, **kwargs)
    except ResearchPacketOutputError:
        coerced = _coerce_exact_json_object(raw)
        if coerced is None:
            raise
        return parse_research_packet_output(
            json.dumps(coerced, ensure_ascii=False),
            **kwargs,
        )


def format_research_packet_context(packets: Mapping[str, ResearchPacket]) -> str:
    "Full diagnostic serialization; workers use memory.research_context views."
    if not packets:
        return "[]"
    return json.dumps(
        [
            packet.model_dump(mode="json", exclude_none=True)
            for packet in packets.values()
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
