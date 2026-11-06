"""需求处理入口。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from langchain_core.runnables import RunnableConfig

from travel_agent.conversation.compaction import _check_and_handle_compaction_deep
from travel_agent.planning.requirements.understanding.prompts import understanding_system_prompt
from travel_agent.planning.state import TravelAgentState

if TYPE_CHECKING:
    from travel_agent.runtime.events import EventBuffer


logger = logging.getLogger(__name__)


async def clarifier_node(
    state: TravelAgentState, config: Optional[RunnableConfig] = None
) -> Dict[str, Any]:
    """Scope（需求范围检查）阶段：压缩入口会话并检查运行前提。

    旅行基础信息由理解节点确认；此处不校验其是否完整。
    """

    stream_queue: Optional["EventBuffer"] = None
    if config is not None:
        stream_queue = config.get("configurable", {}).get("stream_queue")

    try:
        compaction_updates = await _check_and_handle_compaction_deep(
            state,
            stream_queue,
            understanding_system_prompt(),
        )
    except Exception as e:
        logger.warning("Clarifier: 会话大小测量失败，降级为当前请求与会话: %s", e)
        compaction_updates = {}

    logger.info("Clarifier: 会话整理完成，进入需求理解")
    return compaction_updates
