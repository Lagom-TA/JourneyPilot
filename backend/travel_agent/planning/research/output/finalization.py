from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Mapping, Sequence

from travel_agent.planning.research.evidence import SourceRecord
from travel_agent.planning.research.packets import ResearchPacket

from .failures import _merge_failed_tool_sources
from .parsing import _parse_packet_lenient_first
from .policy import ResearchPacketOutputError, ResearchWorkerKind
from .transcript import authoritative_tool_messages

logger = logging.getLogger(__name__)

_REASK_REASON_LIMIT = 300


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
    """只解析一次 worker 返回值；失败后是否重新请求模型由调用方决定。"""
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


async def parse_research_packet_or_reask(
    raw: str,
    *,
    reask: Callable[[str], Awaitable[str]],
    expected_worker: ResearchWorkerKind,
    **parse_kwargs: Any,
) -> ResearchPacket:
    """首次解析失败时让模型按同一批证据重新输出一次，再失败才交给 worker 失败协议。

    只重试输出本身无法解析的情形（``ResearchPacketOutputError``）；``reask`` 自身的
    异常（供应商错误、研究窗口关闭、取消）原样抛出，不再包一层重试。最多重新请求一次，
    因为每次重试都是一次付费调用并占用研究时限。
    """
    try:
        return await parse_research_packet(raw, expected_worker=expected_worker, **parse_kwargs)
    except ResearchPacketOutputError as exc:
        reason = str(exc)[:_REASK_REASON_LIMIT]
        logger.warning("worker=%s Research Packet 首次解析失败，重新请求一次: %s", expected_worker, reason)
        second = await reask(reason)
        return await parse_research_packet(second or "", expected_worker=expected_worker, **parse_kwargs)

