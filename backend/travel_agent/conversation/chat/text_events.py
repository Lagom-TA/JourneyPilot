from __future__ import annotations
from typing import Any, AsyncIterator, Dict
from travel_agent.planning.presentation import (
    get_agent_display_name,
    get_step_display_name,
)
from travel_agent.runtime.events import run_ts_ms

from .presentation import ChatPresentation


async def _handle_token(
    item: tuple, ctx: ChatPresentation
) -> AsyncIterator[Dict[str, Any]]:
    """token 事件：Worker 节点 astream() 的实时 token（synthesizer 的最终输出）。"""
    _, node_name, chunk = item
    ctx.streamed_nodes.add(node_name)
    ctx.final_agent_name = get_agent_display_name(node_name)
    ctx.final_step_name = get_step_display_name(node_name)

    if ctx.use_deep_research:
        return
    display = ctx.stripper.feed(chunk)
    if display:
        yield {
            "type": "chat_chunk",
            "message_id": ctx.message_id,
            "content": display,
            "show_content": display,
            "ts_ms": run_ts_ms(),
        }
