"""Research packet parsing responsibilities."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Mapping, Optional, Sequence

from pydantic import ValidationError

from travel_agent.entities.provider_evidence import ProviderEvidenceScope
from travel_agent.knowledge.source_records import rag_chunk_source_records
from travel_agent.planning.research.evidence import SourceRecord
from travel_agent.planning.research.packets import (
    RESEARCH_PACKET_IDENTITY_FACTS_MISSING,
    ResearchPacket,
)
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
from .options import _eligible_place_selection_options, _has_eligible_place_selection
from .policy import (
    _WORKER_CANDIDATE_MODELS,
    ResearchPacketOutputError,
    ResearchWorkerKind,
    packet_candidate_limit,
)
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
    required_transport_classes: Sequence[str] | None = None,
    excluded_candidate_ids: Sequence[str] | None = None,
    require_current_candidate: bool = False,
    expected_active_constraint_ids: Sequence[str] | None = None,
    context_messages: Sequence[Mapping[str, Any]] = (),
    authoritative_tool_results: Sequence[Mapping[str, Any]] = (),
    authoritative_packet_metadata: Mapping[str, Any] | None = None,
    required_candidate_kinds: Sequence[str] | None = None,
    authoritative_source_records: Sequence[SourceRecord] = (),
    required_route_scopes: Sequence[ProviderEvidenceScope] = (),
    server_composed_candidate_limit: int | None = None,
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
    if not isinstance(payload, dict):
        raise ResearchPacketOutputError("worker output must be one JSON object")
    _bind_authoritative_packet_metadata(payload, authoritative_packet_metadata)
    candidates = payload.get("candidates")
    candidate_limit = (
        server_composed_candidate_limit
        if server_composed_candidate_limit is not None
        else packet_candidate_limit(
            expected_worker,
            required_transport_classes=required_transport_classes,
            required_route_scopes=required_route_scopes,
        )
    )
    if isinstance(candidates, list) and len(candidates) > candidate_limit:
        raise ResearchPacketOutputError(
            f"worker Research Packet exceeds candidate limit {candidate_limit}"
        )
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
        compiled_failure_source_ids = [
            source_id
            for source_id, source in compiled_tool_sources.items()
            if source.lifecycle_status == "rejected"
        ]
        # Rendered validation text contains untrusted model data, not failure authority.
        _identity_facts_missing = any(
            err.get("type") == RESEARCH_PACKET_IDENTITY_FACTS_MISSING
            for err in exc.errors()
        )
        if not _identity_facts_missing or not compiled_failure_source_ids:
            raise ResearchPacketOutputError(
                f"worker Research Packet failed schema gate: {exc}"
            ) from exc
        logger.warning(
            "Research Packet candidate closure dropped (failed/degraded sources only) | "
            "worker=%s dropped_candidates=%d dropped_facts=%d dropped_provenance=%d "
            "candidate_ids=%s failed_source_ids=%s validation_error=%s",
            expected_worker,
            len(payload.get("candidates") or []),
            len(payload.get("fact_assertions") or []),
            len(payload.get("field_provenance") or []),
            ",".join(
                str(candidate.get("candidate_id") or "<unnamed>")
                for candidate in (payload.get("candidates") or [])
                if isinstance(candidate, Mapping)
            )
            or "-",
            ",".join(compiled_failure_source_ids) or "-",
            str(exc)[:400],
        )
        failed_payload = {
            **payload,
            "candidates": [],
            "fact_assertions": [],
            "field_provenance": [],
        }
        try:
            packet = ResearchPacket.model_validate(failed_payload)
        except ValidationError:
            raise ResearchPacketOutputError(
                f"worker Research Packet failed schema gate: {exc}"
            ) from exc
    if packet.worker_kind != expected_worker:
        raise ResearchPacketOutputError(
            "worker Research Packet domain does not match the node"
        )
    if packet.run_id != expected_run_id:
        raise ResearchPacketOutputError(
            "worker Research Packet run id does not match active run"
        )
    if required_candidate_kinds:
        allowed_kinds = {
            candidate_kind
            for candidate_kind, _ in _WORKER_CANDIDATE_MODELS[expected_worker]
        }
        required_kinds = set(required_candidate_kinds)
        if not required_kinds <= allowed_kinds:
            raise ResearchPacketOutputError(
                "required candidate kinds do not belong to the active worker"
            )
        missing_kinds = required_kinds - {
            candidate.candidate_kind for candidate in packet.candidates
        }
        if missing_kinds:
            raise ResearchPacketOutputError(
                "worker Research Packet is missing required candidate kinds: "
                f"{','.join(sorted(missing_kinds))}"
            )
    eligible_place_options = _eligible_place_selection_options(
        evidence_messages,
        expected_worker,
        excluded_candidate_ids=excluded_candidate_ids,
    )
    if not packet.candidates and _has_eligible_place_selection(eligible_place_options):
        raise ResearchPacketOutputError(
            "worker returned zero candidates despite eligible Provider place records"
        )
    if expected_active_constraint_ids is not None:
        expected_constraints = set(expected_active_constraint_ids)
        for candidate in packet.candidates:
            if set(candidate.active_constraint_ids) != expected_constraints:
                raise ResearchPacketOutputError(
                    "candidate active constraints do not match the authoritative constraint pack"
                )
            if {
                evaluation.constraint_id
                for evaluation in candidate.constraint_evaluations
            } != expected_constraints:
                raise ResearchPacketOutputError(
                    "candidate constraint evaluations do not cover the authoritative active constraints"
                )
    forbidden = set(excluded_candidate_ids or [])
    if forbidden & {candidate.candidate_id for candidate in packet.candidates}:
        raise ResearchPacketOutputError(
            "worker Research Packet repeated a candidate excluded by the active gap"
        )
    if required_transport_classes and any(
        getattr(candidate, "transport_class", None) not in required_transport_classes
        for candidate in packet.candidates
    ):
        raise ResearchPacketOutputError(
            "transport Research Packet does not match the scoped transport classes"
        )
    allowed_route_scope_ids = {scope.scope_id for scope in required_route_scopes}
    if required_route_scopes and any(
        candidate.candidate_kind == "transport"
        and candidate.transport_class == "long_distance"
        and candidate.provider_evidence_scope_id not in allowed_route_scope_ids
        for candidate in packet.candidates
    ):
        raise ResearchPacketOutputError(
            "long-distance candidate does not match an assigned exact route leg"
        )
    if (
        require_current_candidate
        and packet.candidates
        and not any(
            candidate.freshness_status == "current" for candidate in packet.candidates
        )
    ):
        raise ResearchPacketOutputError(
            "scoped Research Packet did not produce a current candidate"
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
