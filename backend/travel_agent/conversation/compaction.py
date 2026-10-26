"""会话上下文压缩。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from travel_agent.conversation.history import session_history_for_context_builder
from travel_agent.planning.state import TravelAgentState

if TYPE_CHECKING:
    from travel_agent.runtime.events import EventBuffer


logger = logging.getLogger(__name__)


_CLARIFIER_NODE = "scope_clarifier"


async def _measure_session_size(
    state: TravelAgentState,
    system_prompt: str,
) -> Optional[Any]:
    """估算本次会话的上下文大小，用于判断是否需要压缩。"""
    from travel_agent.memory.compressor import AnchorSummary
    from travel_agent.memory.context_builder import ContextBuilder

    raw_history = session_history_for_context_builder(state)

    session_anchor_obj = None
    if state.session_anchor:
        try:
            session_anchor_obj = AnchorSummary.from_dict(state.session_anchor)
        except Exception as e:
            logger.debug("AnchorSummary 解析失败（Scope 上下文）: %s", e)

    return await ContextBuilder().build_context(
        session_id=state.session_id or "",
        system_prompt=system_prompt,
        recent_messages=raw_history,
        session_anchor=session_anchor_obj,
        session_compressed=state.session_compressed,
    )


async def _check_and_handle_compaction_deep(
    state: TravelAgentState,
    stream_queue: Optional["EventBuffer"],
    system_prompt: str,
) -> dict:
    """Deep 模式入口：检测是否需要压缩上下文，返回要更新到 state 的压缩字段。"""

    built_ctx = await _measure_session_size(state, system_prompt)
    if built_ctx is None:
        return {}

    compaction_updates: dict = {}
    if built_ctx.needs_compaction and stream_queue is not None:
        from travel_agent.memory.compaction import (
            CompactionBusy,
            get_compaction_service,
        )

        try:
            result = await get_compaction_service().compact(
                user_id=state.user_id or "",
                session_id=state.session_id or "",
                source="automatic",
            )
        except CompactionBusy:
            logger.info("Scope: 会话已有压缩在进行，本轮沿用原上下文")
            result = None
        except Exception as e:
            logger.error(f"Scope: Deep 模式自动压缩失败: {e}")
            result = None
        if result is not None:
            await stream_queue.put(
                ("context_compaction", _CLARIFIER_NODE, result.event)
            )
            compaction_updates = {
                "session_anchor": result.anchor.to_dict(),
                "session_compressed": True,
                "session_compacted_this_turn": True,
            }

    return compaction_updates
