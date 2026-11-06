from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence

from travel_agent.llm.task_routing import plain_observation_messages
from travel_agent.planning.research.evidence import SourceRecord
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.runtime.cancellation import RunCancelled
from travel_agent.storage.worker_journal_store import JournalConflict

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
    llm: Any,
    messages: Sequence[Mapping[str, Any]],
    expected_worker: ResearchWorkerKind,
    degrade_on_reask_error: bool = False,
    **parse_kwargs: Any,
) -> ResearchPacket:
    """首次解析失败时让模型按同一批工具观察重新输出一次，再失败才交给 worker 失败协议。

    只重试输出本身无法解析的情形（``ResearchPacketOutputError``）；最多重新请求一次，
    因为每次重试都是一次付费调用并占用研究时限。重新请求自身的异常（供应商错误、
    研究窗口关闭）默认原样抛出、不再重试；调用方另有不依赖模型的保底路径时，传
    ``degrade_on_reask_error`` 把这类异常转成 ``ResearchPacketOutputError``，让它照常走保底。
    取消类异常任何情况下都不吞掉。
    """
    try:
        return await parse_research_packet(raw, expected_worker=expected_worker, **parse_kwargs)
    except ResearchPacketOutputError as exc:
        reason = str(exc)[:_REASK_REASON_LIMIT]
        logger.warning("worker=%s Research Packet 首次解析失败，重新请求一次: %s", expected_worker, reason)
        try:
            second = await llm.ainvoke(
                [
                    *plain_observation_messages(messages),
                    {
                        "role": "user",
                        "content": (
                            f"上一次输出无法解析为 Research Packet：{reason}\n"
                            "请基于上面的工具观察重新输出完整结果：只输出一个合法的 JSON 对象，"
                            "不要使用 Markdown 围栏，不要附加说明文字。"
                        ),
                    },
                ],
                response_format={"type": "json_object"},
            )
        except (RunCancelled, JournalConflict):
            raise
        except Exception as reask_exc:
            if not degrade_on_reask_error:
                raise
            logger.warning("worker=%s 重新请求失败，按无法解析处理: %s", expected_worker, type(reask_exc).__name__)
            raise ResearchPacketOutputError(
                f"重新请求失败: {type(reask_exc).__name__}"
            ) from reask_exc
        return await parse_research_packet(second or "", expected_worker=expected_worker, **parse_kwargs)
