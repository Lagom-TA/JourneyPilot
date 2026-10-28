from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping, Sequence

from travel_agent.planning.research.provider_contracts import ProviderEvidenceOutcome
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
    """从 Tool Gateway 信封直接编译被拒绝的失败来源记录。"""
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
    """把执行失败记录写入 packet，不依赖模型撰写的 JSON。"""
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


def build_failure_only_research_packet(
    *,
    authoritative_packet_metadata: Mapping[str, Any],
    context_messages: Sequence[Mapping[str, Any]],
) -> ResearchPacket | None:
    """packet 序列化失败时，单独持久化被拒绝的执行失败记录。"""
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
    """判断本轮是否仅为「Provider 正常应答但没有结果」。"""
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
    """判断本轮是否仅为「Provider 声明无法回答该日期」。"""
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
