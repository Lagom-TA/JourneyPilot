from __future__ import annotations

from typing import Any, Mapping, Sequence

from travel_agent.planning.research.evidence import SourceRecord
from travel_agent.planning.research.packets import ResearchPacket

from .failures import _merge_failed_tool_sources
from .parsing import _parse_packet_lenient_first
from .policy import ResearchWorkerKind
from .transcript import authoritative_tool_messages


async def parse_research_packet(
    raw: str,
    *,
    expected_worker: ResearchWorkerKind,
    expected_run_id: str,
    authoritative_tool_results: Sequence[Mapping[str, Any]] = (),
    expected_active_constraint_ids: Sequence[str] | None = None,
    authoritative_packet_metadata: Mapping[str, Any] | None = None,
    authoritative_source_records: Sequence[SourceRecord] = (),
) -> ResearchPacket:
    """只解析一次 worker 返回值；失败交由 worker 失败协议处理，不做模型驱动的修复重试。"""
    evidence_messages = authoritative_tool_messages(authoritative_tool_results)
    packet = _parse_packet_lenient_first(
        raw,
        expected_worker=expected_worker,
        expected_run_id=expected_run_id,
        expected_active_constraint_ids=expected_active_constraint_ids,
        authoritative_tool_results=authoritative_tool_results,
        authoritative_packet_metadata=authoritative_packet_metadata,
        authoritative_source_records=authoritative_source_records,
    )
    return _merge_failed_tool_sources(packet, evidence_messages)
