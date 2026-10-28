"""会话回答节点。"""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from travel_agent.conversation.answer.prompts import (
    DISCOVERY_OBJECTIVE_INSTRUCTION,
    SYSTEM_PROMPT,
)
from travel_agent.conversation.answer.tool_context import (
    _NODE_NAME,
    _build_realtime_tool_context,
)
from travel_agent.conversation.history import session_history_for_context_builder
from travel_agent.llm.router import get_model_router
from travel_agent.llm.task_routing import TaskKind, llm_for_task
from travel_agent.memory.context_builder import ContextBudget, ContextBuilder
from travel_agent.planning.requirements.constraints.loading import (
    build_run_constraint_pack,
)
from travel_agent.planning.requirements.constraints.presentation import (
    format_constraint_pack_for_prompt,
    referenced_context_sections,
)
from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.tool_context import build_tool_context_from_state
from travel_agent.tools.access import filter_tools_for_agent, get_available_tools
from travel_agent.tools.react import streaming_react_loop

if TYPE_CHECKING:
    from travel_agent.runtime.events import EventBuffer


logger = logging.getLogger(__name__)


async def fast_answer_node(
    state: TravelAgentState, config: RunnableConfig
) -> Dict[str, Any]:
    """快速回答 Agent 节点。"""
    router = get_model_router()

    stream_queue: Optional["EventBuffer"] = config.get("configurable", {}).get(
        "stream_queue"
    )

    llm = llm_for_task(router, TaskKind.QUICK_ANSWER)
    user_query = state.user_query or ""
    current_time = state.current_time or datetime.datetime.now().strftime(
        "%Y-%m-%d %H:%M"
    )

    preset_suffix = ""
    if state.preset_context:
        from travel_agent.conversation.preset_context import PresetInjector

        preset_suffix = PresetInjector.format_for_agent(state.preset_context)

    constraint_pack = await build_run_constraint_pack(state)
    constraint_text = format_constraint_pack_for_prompt(constraint_pack)

    base_system = SYSTEM_PROMPT.format(current_time=current_time)
    if preset_suffix:
        base_system += preset_suffix
    if constraint_text:
        base_system += "\n\n" + constraint_text

    raw_history = session_history_for_context_builder(state)

    from travel_agent.memory.compressor import AnchorSummary

    session_anchor_obj = None
    if state.session_anchor:
        try:
            session_anchor_obj = AnchorSummary.from_dict(state.session_anchor)
        except Exception as e:
            logger.debug(f"FastAnswer: Anchor 解析失败: {e}")

    from travel_agent.config.loader import get_settings

    ctx_builder = ContextBuilder(
        ContextBudget(response_reserve=get_settings().fast_model.max_tokens)
    )
    built_ctx = await ctx_builder.build_context(
        session_id=state.session_id or "",
        system_prompt=base_system,
        recent_messages=raw_history,
        session_anchor=session_anchor_obj,
        session_compressed=state.session_compressed,
    )

    context_compaction: Dict[str, Any] = {"triggered": False}
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
            logger.info("FastAnswer: 会话已有压缩在进行，本轮沿用原上下文")
            result = None
        except Exception as e:
            logger.error(f"FastAnswer: 自动压缩失败，继续使用原始上下文: {e}")
            result = None
        if result is not None:
            anchor = result.anchor
            session_anchor_obj = anchor
            context_compaction = {
                "triggered": True,
                "tokens_before": anchor.tokens_before,
                "tokens_after": anchor.tokens_after,
                "messages_compressed": anchor.messages_compressed,
                "summary_preview": anchor.summary[:200]
                + ("..." if len(anchor.summary) > 200 else ""),
            }
            await stream_queue.put(("context_compaction", _NODE_NAME, result.event))
            built_ctx = await ctx_builder.build_context(
                session_id=state.session_id or "",
                system_prompt=base_system,
                recent_messages=raw_history,
                session_anchor=session_anchor_obj,
                session_compressed=True,
            )

    if stream_queue is not None:
        from travel_agent.memory.context_builder import build_context_report

        report = build_context_report(
            referenced_sections=referenced_context_sections(constraint_pack),
            compaction=context_compaction,
        )
        if report is not None:
            await stream_queue.put(("context_report", _NODE_NAME, report))

    realtime_context = await _build_realtime_tool_context(
        state=state, stream_queue=stream_queue
    )
    realtime_prompt = str(realtime_context.get("prompt") or "")
    wire_tail = []
    if str((state.route_decision or {}).get("route") or "") == "destination_discovery":
        wire_tail.append({"role": "system", "content": DISCOVERY_OBJECTIVE_INSTRUCTION})
    if realtime_prompt:
        wire_tail.append({"role": "user", "content": realtime_prompt})
    wire_tail.append({"role": "user", "content": f"用户问题：{user_query}"})

    built_ctx = await ctx_builder.build_context(
        session_id=state.session_id or "",
        system_prompt=base_system,
        recent_messages=raw_history,
        session_anchor=session_anchor_obj,
        session_compressed=state.session_compressed,
        runtime_messages=wire_tail,
    )
    messages = [
        {"role": "system", "content": built_ctx.system_prompt},
        *built_ctx.messages,
        *wire_tail,
    ]

    try:
        available_tools = filter_tools_for_agent(
            await get_available_tools(state.selected_mcp_servers or []),
            _NODE_NAME,
        )
        react = await streaming_react_loop(
            llm=llm,
            messages=messages,
            available_tools=available_tools,
            stream_queue=stream_queue,
            node_name=_NODE_NAME,
            max_iterations=3,
            tool_context=build_tool_context_from_state(state),
            # 回答节点输出自然语言答复，不要求 Research Packet 正文。
            final_round_notice=None,
        )
        response = react.require_final_answer()
        logger.info(f"FastAnswer 生成回答，长度: {len(response)}")
        if stream_queue is not None:
            await stream_queue.put(("token", _NODE_NAME, response))
        return {
            "constraint_pack": constraint_pack,
            "constraint_pack_revision": state.constraint_pack_revision + 1,
            "messages": [AIMessage(content=response)],
            "is_completed": True,
            "synthesis_mode": "fast",
        }

    except Exception as e:
        logger.error(f"FastAnswer 执行失败: {e}")
        raise
