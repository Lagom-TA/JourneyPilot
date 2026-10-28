from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict
from travel_agent.planning.research.progress import worker_result
from travel_agent.planning.presentation import (
    get_agent_display_name,
    get_step_display_name,
)
from travel_agent.utils.json_helpers import strip_think_blocks
from travel_agent.planning.delivery.public.bundle import public_event_manifest
from travel_agent.conversation.stream_text import (
    StreamingStripper,
    strip_non_display_blocks,
)
from travel_agent.planning.trace import summarize_state_update
from travel_agent.runtime.events import node_timing_registry, run_ts_ms
from travel_agent.conversation.stream_text import strip_thinking_text

from .presentation import ChatPresentation

_DEEP_WORKER_NODES = {
    "destination_researcher",
    "transport_researcher",
    "accommodation_researcher",
    "itinerary_planner",
}
_FINAL_OUTPUT_NODES = {"fast_answer_agent"}
_PROGRESS_STEP_NODES = {
    "request_contract_normalizer",
    "research_brief_builder",
    "intent_amendment_router",
    "destination_geo_resolver",
    "weather_context_builder",
    "dispatcher",
}
_DISPATCHER_PROGRESS_TEXT = "正在分派并行调研任务"


async def _handle_agent_activity(
    item: tuple, ctx: ChatPresentation
) -> AsyncIterator[Dict[str, Any]]:
    _, node_name, _ = item
    name = get_agent_display_name(node_name)
    previous = next(
        (
            step
            for step in reversed(ctx.thinking_steps)
            if step.get("agent_name") == name and step.get("progress_status")
        ),
        None,
    )
    if (
        previous
        and previous.get("progress_status") == "running"
        and not previous.get("end_time")
    ):
        return
    now = datetime.now(timezone.utc).isoformat()
    content = "正在整理需求并查询相关资料"
    ctx.thinking_steps.append(
        {
            "step_id": str(uuid.uuid4()),
            "agent_name": name,
            "step_name": name,
            "content": content,
            "timestamp": now,
            "progress_status": "running",
        }
    )
    yield {
        "type": "agent_progress",
        "message_id": ctx.message_id,
        "agent_name": name,
        "step_name": name,
        "content": content,
        "progress_status": "running",
        "ts_ms": run_ts_ms(),
    }


async def _handle_node_activity(
    payload: Dict[str, Any], ctx: ChatPresentation
) -> AsyncIterator[Dict[str, Any]]:
    node = str(payload.get("node") or "")
    if payload.get("status") == "started" and node in _DEEP_WORKER_NODES:
        async for event in _handle_agent_activity(("agent_activity", node, None), ctx):
            yield event


async def _handle_context_report(
    item: tuple, ctx: ChatPresentation
) -> AsyncIterator[Dict[str, Any]]:
    """context_report 事件：按预算装配的上下文报告。

    随本轮助手消息持久化（save_turn），加载会话历史时可取回。
    """
    _, _node, report = item
    ctx.context_report = report
    yield {
        "type": "context_report",
        "message_id": ctx.message_id,
        **report,
    }


async def _handle_context_compaction(
    item: tuple, ctx: ChatPresentation
) -> AsyncIterator[Dict[str, Any]]:
    """持久化并下发本轮完整的上下文压缩快照。"""
    _, _node, event = item

    yield {
        "type": "context_compaction",
        "message_id": ctx.message_id,
        **event,
    }


async def _handle_state_update(
    item: tuple, ctx: ChatPresentation
) -> AsyncIterator[Dict[str, Any]]:
    """state 事件：节点完成处理。

    处理顺序：
      1. 若节点曾流式输出，flush stripper 残留；
      2. planner 节点：发送 thinking 并记录执行计划；
      3. 其他节点：处理 pending_user_choice、深度 Worker 与最终输出；
      4. 记录节点完成 trace。
    """
    _, node_name, state_update = item
    if state_update is None:
        return
    if isinstance(state_update, dict) and state_update.get("run_id"):
        ctx.trace_run_id = str(state_update.get("run_id"))
    delivery = (
        state_update.get("delivery_bundle") if isinstance(state_update, dict) else None
    )
    if hasattr(delivery, "model_dump"):
        delivery = delivery.model_dump(mode="json")
    if isinstance(delivery, dict) and isinstance(delivery.get("manifest"), dict):
        ctx.delivery_manifest = public_event_manifest(delivery["manifest"])
        ctx.delivery_bundle_id = (
            str(delivery["manifest"].get("bundle_id") or "") or None
        )

    if node_name == "__final_state__":
        yield ctx.next_trace(
            node="workflow",
            phase="postprocess",
            status="completed",
            output_summary="workflow final state received",
        )

        return

    summary_card = (
        state_update.get("trip_summary_card")
        if isinstance(state_update, dict)
        else None
    )
    if isinstance(summary_card, dict):
        ctx.trip_summary_card = summary_card
        yield {
            "type": "trip_summary_card",
            "message_id": ctx.message_id,
            "run_id": ctx.trace_run_id,
            "summary_card": summary_card,
            "ts_ms": run_ts_ms(),
        }

    if node_name in ctx.streamed_nodes:
        remaining = ctx.stripper.flush()
        if remaining and not ctx.use_deep_research:
            yield {
                "type": "chat_chunk",
                "message_id": ctx.message_id,
                "content": remaining,
                "show_content": remaining,
                "ts_ms": run_ts_ms(),
            }
        ctx.stripper = StreamingStripper()

    if (
        node_name in _PROGRESS_STEP_NODES
        and node_name not in ctx.progress_nodes_emitted
    ):
        ctx.progress_nodes_emitted.add(node_name)
        progress_step_name = get_step_display_name(node_name)

        progress_content = (
            _DISPATCHER_PROGRESS_TEXT if node_name == "dispatcher" else ""
        )
        yield {
            "type": "thinking",
            "message_id": ctx.message_id,
            "agent_name": get_agent_display_name(node_name),
            "content": progress_content,
            "step_name": progress_step_name,
            "ts_ms": run_ts_ms(),
        }
        now_iso = datetime.now(timezone.utc).isoformat()
        ctx.thinking_steps.append(
            {
                "step_id": str(uuid.uuid4()),
                "agent_name": get_agent_display_name(node_name),
                "step_name": progress_step_name,
                "content": progress_content,
                "timestamp": now_iso,
                "end_time": now_iso,
            }
        )

    if node_name == "planner":
        tt = state_update.get("task_type")
        if tt is not None:
            ctx.task_type = tt.value if hasattr(tt, "value") else str(tt)

        execution_plan = state_update.get("execution_plan", [])
        if execution_plan:
            agents_desc = " → ".join(
                "/".join(get_agent_display_name(a) for a in g) for g in execution_plan
            )
            thinking_content = f"制定调研计划：{agents_desc}"
        else:
            thinking_content = "制定调研计划中..."

        yield {
            "type": "thinking",
            "message_id": ctx.message_id,
            "agent_name": get_agent_display_name("planner"),
            "content": thinking_content,
            "step_name": get_step_display_name("planning"),
            "ts_ms": run_ts_ms(),
        }
        now_iso = datetime.now(timezone.utc).isoformat()
        ctx.thinking_steps.append(
            {
                "step_id": str(uuid.uuid4()),
                "agent_name": get_agent_display_name("supervisor"),
                "step_name": get_step_display_name("orchestrating"),
                "content": thinking_content,
                "timestamp": now_iso,
                "end_time": now_iso,
            }
        )

    else:
        if ctx.use_deep_research and node_name in _DEEP_WORKER_NODES:
            name = get_agent_display_name(node_name)
            ctx.final_agent_name = name
            ctx.final_step_name = get_step_display_name(node_name)
            now = datetime.now(timezone.utc).isoformat()
            progress_status, content, preview = worker_result(node_name, state_update)
            for step in ctx.thinking_steps:
                if (
                    step.get("agent_name") == name
                    and step.get("progress_status") == "running"
                ):
                    step["end_time"] = now
            yield {
                "type": "agent_progress",
                "message_id": ctx.message_id,
                "agent_name": name,
                "step_name": get_step_display_name(node_name),
                "content": content,
                "progress_status": progress_status,
                "result_preview": preview,
                "ts_ms": run_ts_ms(),
            }
            ctx.thinking_steps.append(
                {
                    "step_id": str(uuid.uuid4()),
                    "agent_name": name,
                    "step_name": get_step_display_name(node_name),
                    "content": content,
                    "timestamp": now,
                    "end_time": now,
                    "progress_status": progress_status,
                    "result_preview": preview,
                }
            )
        elif node_name not in ctx.streamed_nodes and not ctx.use_deep_research:
            messages_list = state_update.get("messages", [])
            if messages_list:
                last_msg = messages_list[-1]
                raw_content = (
                    last_msg.content if hasattr(last_msg, "content") else str(last_msg)
                )
                content = (
                    raw_content if isinstance(raw_content, str) else str(raw_content)
                )
                ctx.full_response = content
                display_content = strip_non_display_blocks(
                    strip_thinking_text(strip_think_blocks(content))
                )
                ctx.final_agent_name = get_agent_display_name(node_name)
                ctx.final_step_name = get_step_display_name(node_name)
                yield {
                    "type": "chat_chunk",
                    "message_id": ctx.message_id,
                    "content": display_content,
                    "show_content": display_content,
                    "ts_ms": run_ts_ms(),
                }
        else:
            if node_name in _FINAL_OUTPUT_NODES:
                messages_list = state_update.get("messages", [])
                if messages_list:
                    last_msg = messages_list[-1]
                    raw_content = (
                        last_msg.content
                        if hasattr(last_msg, "content")
                        else str(last_msg)
                    )
                    ctx.full_response = (
                        raw_content
                        if isinstance(raw_content, str)
                        else str(raw_content)
                    )
                    ctx.final_agent_name = get_agent_display_name(node_name)
                    ctx.final_step_name = get_step_display_name(node_name)

    node_timing = node_timing_registry.pop(ctx.trace_run_id, node_name)
    trace_bits = summarize_state_update(node_name, state_update)
    yield ctx.next_trace(
        node=node_name,
        status="completed",
        output_summary=trace_bits.get("output_summary"),
        route_decision=trace_bits.get("route_decision"),
        risk_flags=trace_bits.get("risk_flags"),
        ts_ms=node_timing.get("ts_ms") if node_timing else None,
        duration_ms=node_timing.get("duration_ms") if node_timing else None,
    )
