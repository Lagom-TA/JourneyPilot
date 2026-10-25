"""Planning requirements entry."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from langchain_core.runnables import RunnableConfig

from travel_agent.conversation.compaction import _check_and_handle_compaction_deep
from travel_agent.conversation.compaction_prompt import SCOPE_CONTEXT_SYSTEM_PROMPT
from travel_agent.planning.state import TravelAgentState

if TYPE_CHECKING:
    from travel_agent.runtime.events import EventBuffer


logger = logging.getLogger(__name__)


class ScopeIdentityError(RuntimeError):
    """Scope 阶段拿不到受控旅行身份。"""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        super().__init__(
            f"run {run_id or '<unknown>'} reached scope without a controlled trip identity"
        )


async def clarifier_node(
    state: TravelAgentState, config: Optional[RunnableConfig] = None
) -> Dict[str, Any]:
    """Scope 阶段 — 步骤 1：入口与前提守卫"""
    stream_queue: Optional["EventBuffer"] = None
    if config is not None:
        stream_queue = config.get("configurable", {}).get("stream_queue")

    try:
        compaction_updates = await _check_and_handle_compaction_deep(
            state,
            stream_queue,
            SCOPE_CONTEXT_SYSTEM_PROMPT,
        )
    except Exception as e:
        logger.warning("Clarifier: 会话大小测量失败，降级为当前请求与会话: %s", e)
        compaction_updates = {}

    if not state.controlled_trip_identity:
        logger.error(
            "Clarifier: run %s 缺少受控旅行身份，拒绝继续", state.run_id or "<unknown>"
        )
        raise ScopeIdentityError(state.run_id or "")

    logger.info("Clarifier: 受控旅行身份已确认，进入请求合同归一化")
    return compaction_updates
