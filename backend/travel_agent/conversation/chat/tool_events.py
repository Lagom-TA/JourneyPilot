from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict
from travel_agent.tools.display import public_text, result_preview
from travel_agent.tools.governance import (
    CAPABILITY_DECLARATION_STATUSES,
    ToolExecutionStatus,
)
from travel_agent.planning.presentation import get_agent_display_name

from .presentation import ChatPresentation

_TOOL_OUTCOME_CAPABILITY_DECLARED = "capability_declared"
_TOOL_OUTCOME_COMPLETED = "completed"
_TOOL_OUTCOME_FAILED = "failed"

_FAILED_TOOL_STATUSES = frozenset(
    {
        ToolExecutionStatus.FAILED.value,
        ToolExecutionStatus.BLOCKED.value,
    }
)


def _tool_outcome(tool_status: str) -> str:
    """把一个 ToolExecutionStatus 映射成面向用户的工具轮次结论。

    ``degraded`` 仍然是「拿到了可用结果」，所以结论是 completed，降级事实由
    ``risk_flags`` 的 ``tool_degraded`` 与帧上的 ``degraded`` 承载（行为不变）。
    """
    if tool_status in CAPABILITY_DECLARATION_STATUSES:
        return _TOOL_OUTCOME_CAPABILITY_DECLARED
    if not tool_status or tool_status in _FAILED_TOOL_STATUSES:
        return _TOOL_OUTCOME_FAILED
    return _TOOL_OUTCOME_COMPLETED


async def _handle_tool_start(
    item: tuple, ctx: ChatPresentation
) -> AsyncIterator[Dict[str, Any]]:
    """'tool_start' kind: Worker Agent 工具调用开始 + 记录 thinking_steps。"""
    _, node_name, tool_info = item
    tool_name = tool_info.get("name", "")
    tool_call_id = tool_info.get("tool_call_id") or str(uuid.uuid4())
    tool_category = tool_info.get("category", "other")
    tool_from_cache = tool_info.get("from_cache", False)
    ts_ms = tool_info.get("ts_ms")
    yield {
        "type": "tool_start",
        "message_id": ctx.message_id,
        "agent_name": get_agent_display_name(node_name),
        "tool_name": tool_name,
        "tool_call_id": tool_call_id,
        "args_summary": tool_info.get("args_summary", ""),
        "category": tool_category,
        "from_cache": tool_from_cache,
        "ts_ms": ts_ms,
    }
    yield ctx.next_trace(
        node=node_name,
        phase="tool",
        status="started",
        agent=get_agent_display_name(node_name),
        input_summary=tool_info.get("args_summary", ""),
        tool_calls=[
            {
                "name": tool_name,
                "status": "started",
                "category": tool_category,
                "from_cache": tool_from_cache,
            }
        ],
        ts_ms=ts_ms,
    )
    now_iso = datetime.now(timezone.utc).isoformat()
    ctx.thinking_steps.append(
        {
            "step_id": tool_call_id,
            "tool_call_id": tool_call_id,
            "agent_name": get_agent_display_name(node_name),
            "step_name": f"调用 {tool_name}",
            "content": tool_info.get("args_summary", ""),
            "timestamp": now_iso,
            "is_tool_call": True,
            "tool_name": tool_name,
            "tool_status": "running",
            "tool_args": tool_info.get("args_summary", ""),
            "tool_category": tool_category,
            "from_cache": tool_from_cache,
        }
    )


async def _handle_tool_done(
    item: tuple, ctx: ChatPresentation
) -> AsyncIterator[Dict[str, Any]]:
    """'tool_done' kind: Worker Agent 工具调用完成 + 更新 thinking_steps 状态。"""
    _, node_name, tool_info = item
    tool_name = tool_info.get("name", "")
    tool_call_id = tool_info.get("tool_call_id")
    tool_summary = public_text(tool_info.get("summary", "")) or "查询已结束"
    preview = result_preview(tool_info.get("result_preview", []))
    tool_category = tool_info.get("category", "other")
    tool_from_cache = tool_info.get("from_cache", False)
    tool_status = str(tool_info.get("status") or "")
    tool_outcome = _tool_outcome(tool_status)
    audit_id = tool_info.get("audit_id")
    degraded = bool(tool_info.get("degraded"))
    duration_ms = tool_info.get("duration_ms")
    ts_ms = tool_info.get("ts_ms")
    fallback_from = tool_info.get("fallback_from")
    fallback_to = tool_info.get("fallback_to")
    tool_result_event: Dict[str, Any] = {
        "type": "tool_result",
        "message_id": ctx.message_id,
        "agent_name": get_agent_display_name(node_name),
        "tool_name": tool_name,
        "tool_call_id": tool_call_id,
        "summary": tool_summary,
        "result_preview": preview,
        "status": tool_status,
        "category": tool_category,
        "from_cache": tool_from_cache,
        "duration_ms": duration_ms,
        "ts_ms": ts_ms,
    }
    if fallback_from:
        tool_result_event["fallback_from"] = fallback_from
    if fallback_to:
        tool_result_event["fallback_to"] = fallback_to
    yield tool_result_event
    trace_tool_call = {
        "name": tool_name,
        "status": tool_status,
        "category": tool_category,
        "from_cache": tool_from_cache,
    }
    if audit_id:
        trace_tool_call["audit_id"] = audit_id
    if degraded:
        trace_tool_call["degraded"] = True
    yield ctx.next_trace(
        node=node_name,
        phase="tool",
        status=tool_outcome,
        agent=get_agent_display_name(node_name),
        output_summary=tool_summary,
        tool_calls=[trace_tool_call],
        risk_flags=(
            ["tool_degraded"]
            if degraded
            else (["tool_failed"] if tool_outcome == _TOOL_OUTCOME_FAILED else [])
        ),
        ts_ms=ts_ms,
        duration_ms=duration_ms,
    )
    now_iso = datetime.now(timezone.utc).isoformat()
    for _ts in reversed(ctx.thinking_steps):
        same_call = bool(tool_call_id) and _ts.get("tool_call_id") == tool_call_id
        fallback_match = (
            not tool_call_id
            and _ts.get("is_tool_call")
            and _ts.get("tool_name") == tool_name
            and _ts.get("tool_status") == "running"
        )
        if same_call or fallback_match:
            _ts["tool_status"] = tool_outcome
            _ts["tool_result"] = tool_summary
            _ts["result_preview"] = preview
            _ts["end_time"] = now_iso
            _ts["duration_ms"] = duration_ms
            break
