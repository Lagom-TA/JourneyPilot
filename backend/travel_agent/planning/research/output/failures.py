"""Research packet failures responsibilities."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping, Sequence

from travel_agent.entities.provider_evidence import ProviderEvidenceOutcome
from travel_agent.planning.research.evidence import SourceRecord
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.tools.governance import (
    CAPABILITY_DECLARATION_STATUSES,
    PROVIDER_RESULT_OUTCOME_EMPTY_SUCCESS,
    PROVIDER_RESULT_OUTCOME_METADATA_KEY,
    ToolExecutionStatus,
)

from .identifiers import _canonical_snapshot_hash
from .transcript import _parse_tool_envelope


def _failed_tool_sources(
    *,
    existing_audit_ids: set[str],
    context_messages: Sequence[Mapping[str, Any]],
    default_retrieved_at: datetime,
) -> list[SourceRecord]:
    "Compile rejected failure records directly from Tool Gateway envelopes."
    additions: list[SourceRecord] = []
    for message in context_messages:
        if message.get("role") != "tool":
            continue
        content = message.get("content")
        try:
            envelope = json.loads(content) if isinstance(content, str) else content
        except json.JSONDecodeError:
            continue
        if not isinstance(envelope, dict):
            continue
        if str(envelope.get("status") or "") in CAPABILITY_DECLARATION_STATUSES:
            continue
        audit_id = str(envelope.get("audit_id") or "").strip()
        failure_detail = str(
            envelope.get("degradation_reason") or envelope.get("error") or ""
        ).strip()
        fallback_from = str(envelope.get("fallback_from") or "").strip()
        if (
            not audit_id
            or audit_id in existing_audit_ids
            or not (failure_detail or fallback_from)
        ):
            continue
        tool_name = fallback_from or str(envelope.get("tool_name") or "external_tool")
        retrieved_at = default_retrieved_at
        raw_retrieved_at = envelope.get("retrieved_at")
        if isinstance(raw_retrieved_at, str) and raw_retrieved_at.strip():
            try:
                retrieved_at = datetime.fromisoformat(
                    raw_retrieved_at.strip().replace("Z", "+00:00")
                )
            except ValueError:
                pass
        snapshot = dict(envelope)
        additions.append(
            SourceRecord(
                source_record_id=f"source_tool_failure_{audit_id}",
                source_kind="external_tool",
                title=f"{tool_name} degradation",
                provider_name=str(
                    envelope.get("server_name")
                    or envelope.get("tool_name")
                    or tool_name
                ),
                public_excerpt=(
                    failure_detail
                    or str(envelope.get("result_summary") or "tool degraded")
                )[:900],
                retrieved_at=retrieved_at,
                content_hash=_canonical_snapshot_hash(snapshot),
                snapshot=snapshot,
                lifecycle_status="rejected",
            )
        )
        existing_audit_ids.add(audit_id)
    return additions


def _merge_failed_tool_sources(
    packet: ResearchPacket,
    context_messages: Sequence[Mapping[str, Any]],
) -> ResearchPacket:
    "Persist execution failures independently of model-authored packet JSON."
    existing_audit_ids = {
        str(source.tool_audit_id or source.snapshot.get("audit_id") or "")
        for source in packet.source_records
        if source.tool_audit_id or source.snapshot.get("audit_id")
    }
    additions = _failed_tool_sources(
        existing_audit_ids=existing_audit_ids,
        context_messages=context_messages,
        default_retrieved_at=packet.generated_at,
    )
    if not additions:
        return packet
    return ResearchPacket.model_validate(
        {
            **packet.model_dump(mode="python"),
            "source_records": [*packet.source_records, *additions],
        }
    )


def _controlled_worker_return_failure_source(
    *,
    authoritative_packet_metadata: Mapping[str, Any],
    controlled_worker_return_failure: Mapping[str, Any],
    default_retrieved_at: datetime,
) -> SourceRecord | None:
    "Build one rejected source for the fixed eval worker-return boundary."
    target = controlled_worker_return_failure.get("eval_target")
    expected_worker = authoritative_packet_metadata.get("worker_kind")
    node_name = controlled_worker_return_failure.get("eval_worker_return_node")
    if not isinstance(target, Mapping) or not isinstance(expected_worker, str):
        return None
    raw_node_names = target.get("node_names")
    scope = target.get("scope")
    expected_targets = {
        "all_content": (
            "destination_researcher",
            "transport_researcher",
            "accommodation_researcher",
        ),
    }
    if (
        controlled_worker_return_failure.get("controlled_eval") is not True
        or controlled_worker_return_failure.get("natural_provider_failure") is not False
        or controlled_worker_return_failure.get("eval_boundary") != "worker_return"
        or not isinstance(raw_node_names, list)
        or not isinstance(scope, str)
        or tuple(raw_node_names) != expected_targets.get(scope)
        or node_name != expected_worker
        or expected_worker not in raw_node_names
    ):
        return None
    plan_hash = str(
        controlled_worker_return_failure.get("eval_plan_hash") or ""
    ).strip()
    plan_id = str(controlled_worker_return_failure.get("eval_plan_id") or "").strip()
    fault_kind = str(
        controlled_worker_return_failure.get("eval_fault_kind") or ""
    ).strip()
    error = str(controlled_worker_return_failure.get("error") or "").strip()
    if not plan_hash or not plan_id or not fault_kind or not error:
        return None
    snapshot = {
        **dict(controlled_worker_return_failure),
        "status": "failed",
        "evidence_allowed": False,
        "worker_kind": expected_worker,
        "source_contract": "controlled_eval_worker_return_failure.v1",
    }
    source_digest = hashlib.sha256(
        (
            f"{authoritative_packet_metadata.get('research_packet_id', '')}\0"
            f"{plan_hash}\0{expected_worker}\0{scope}"
        ).encode("utf-8")
    ).hexdigest()[:24]
    return SourceRecord(
        source_record_id=f"source_worker_return_failure_{source_digest}",
        source_kind="external_tool",
        title=f"{scope} worker boundary failure",
        provider_name="controlled_eval_boundary",
        public_excerpt=error[:900],
        retrieved_at=default_retrieved_at,
        content_hash=_canonical_snapshot_hash(snapshot),
        snapshot=snapshot,
        lifecycle_status="rejected",
    )


def build_failure_only_research_packet(
    *,
    authoritative_packet_metadata: Mapping[str, Any],
    context_messages: Sequence[Mapping[str, Any]],
    controlled_worker_return_failure: Mapping[str, Any] | None = None,
) -> ResearchPacket | None:
    "Persist rejected execution failures when Packet serialization fails."
    generated_at_value = authoritative_packet_metadata.get("generated_at")
    if isinstance(generated_at_value, datetime):
        generated_at = generated_at_value
    elif isinstance(generated_at_value, str):
        try:
            generated_at = datetime.fromisoformat(
                generated_at_value.strip().replace("Z", "+00:00")
            )
        except ValueError:
            return None
    else:
        return None
    sources = _failed_tool_sources(
        existing_audit_ids=set(),
        context_messages=context_messages,
        default_retrieved_at=generated_at,
    )
    if controlled_worker_return_failure is not None:
        controlled_source = _controlled_worker_return_failure_source(
            authoritative_packet_metadata=authoritative_packet_metadata,
            controlled_worker_return_failure=controlled_worker_return_failure,
            default_retrieved_at=generated_at,
        )
        if controlled_source is not None:
            sources.append(controlled_source)
    if not sources:
        return None
    return ResearchPacket.model_validate(
        {
            **authoritative_packet_metadata,
            "candidates": [],
            "source_records": sources,
            "fact_assertions": [],
            "field_provenance": [],
        }
    )


def provider_round_answered_empty(
    context_messages: Sequence[Mapping[str, Any]],
    *,
    outcomes: Mapping[str, ProviderEvidenceOutcome],
) -> bool:
    'Whether this worker round is purely "the Provider answered, found nothing".'
    saw_empty_success = False
    for message in context_messages:
        envelope = _parse_tool_envelope(message)
        if envelope is None:
            continue
        if (
            envelope.get("status") != ToolExecutionStatus.SUCCESS.value
            or envelope.get("error")
            or envelope.get("degradation_reason")
            or envelope.get("fallback_from")
        ):
            return False
        metadata = envelope.get("metadata")
        if (
            isinstance(metadata, Mapping)
            and metadata.get(PROVIDER_RESULT_OUTCOME_METADATA_KEY)
            == PROVIDER_RESULT_OUTCOME_EMPTY_SUCCESS
        ):
            saw_empty_success = True
    if not saw_empty_success:
        return False
    return all(outcome.status == "no_option" for outcome in outcomes.values())


def provider_round_capability_declared(
    context_messages: Sequence[Mapping[str, Any]],
    *,
    outcomes: Mapping[str, ProviderEvidenceOutcome],
) -> bool:
    'Whether this worker round is purely "the Provider cannot answer this date".'
    saw_capability = False
    for message in context_messages:
        envelope = _parse_tool_envelope(message)
        if envelope is None:
            continue
        if str(envelope.get("status") or "") in CAPABILITY_DECLARATION_STATUSES:
            saw_capability = True
            continue
        if (
            envelope.get("status") != ToolExecutionStatus.SUCCESS.value
            or envelope.get("error")
            or envelope.get("degradation_reason")
            or envelope.get("fallback_from")
        ):
            return False
    if not saw_capability:
        return False
    return all(outcome.status == "no_option" for outcome in outcomes.values())
