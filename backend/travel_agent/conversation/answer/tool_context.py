"""Conversation answer tool context."""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

from travel_agent.conversation.answer.exchange_context import (
    _CURRENCY_TOOL_NAME,
    _build_exchange_realtime_context,
    _detect_currency_pair,
    _extract_requested_currency_date,
)
from travel_agent.planning.state import TravelAgentState

if TYPE_CHECKING:
    from travel_agent.runtime.events import EventBuffer


logger = logging.getLogger(__name__)


_NODE_NAME = "fast_answer_agent"


async def _build_realtime_tool_context(
    *,
    state: TravelAgentState,
    stream_queue: Optional["EventBuffer"],
) -> Dict[str, Any]:
    pair = _detect_currency_pair(state.user_query or "")
    if not pair:
        return {"prompt": "", "evidence_records": []}

    base, target = pair
    tool_call_id = f"fast_currency_{uuid.uuid4().hex[:8]}"
    args = {"base_currency": base, "to_currencies": target}
    requested_date = _extract_requested_currency_date(state.user_query or "")
    if requested_date is not None:
        args["requested_date"] = requested_date

    try:
        from travel_agent.bootstrap.registry import get_components
        from travel_agent.runtime.events import run_ts_ms
        from travel_agent.tools.execution import execute_tool
        from travel_agent.tools.registry import get_tool_registry

        registry = get_tool_registry()
        if not registry.has_tool(_CURRENCY_TOOL_NAME):
            context = _build_exchange_realtime_context(
                query=state.user_query or "",
                base=base,
                target=target,
                envelope=None,
            )
            return {"prompt": context["prompt"], "evidence_records": []}

        if stream_queue is not None:
            await stream_queue.put(
                (
                    "tool_start",
                    _NODE_NAME,
                    {
                        "name": _CURRENCY_TOOL_NAME,
                        "tool_call_id": tool_call_id,
                        "args_summary": f"base_currency={base}, to_currencies={target}",
                        "category": "data",
                        "ts_ms": run_ts_ms(),
                    },
                )
            )

        components = get_components()
        started = time.perf_counter()
        envelope = await execute_tool(
            _CURRENCY_TOOL_NAME,
            args,
            allowed_tool_names={_CURRENCY_TOOL_NAME},
            max_retries=1,
            run_id=state.run_id,
            node_name=_NODE_NAME,
            tool_audit_store=getattr(components, "tool_audit_store", None),
            activation_source="fast_realtime_preflight",
        )
        context = _build_exchange_realtime_context(
            query=state.user_query or "",
            base=base,
            target=target,
            envelope=envelope,
        )

        if stream_queue is not None:
            evidence = context.get("evidence")
            summary = (
                evidence.get("title")
                if isinstance(evidence, dict)
                else str(envelope.get("result_summary") or "实时汇率读取失败")
            )
            status = str(envelope.get("status") or "")
            await stream_queue.put(
                (
                    "tool_done",
                    _NODE_NAME,
                    {
                        "name": _CURRENCY_TOOL_NAME,
                        "tool_call_id": tool_call_id,
                        "summary": summary,
                        "status": status,
                        "audit_id": envelope.get("audit_id"),
                        "degraded": status == "degraded",
                        "category": "data",
                        "duration_ms": round(
                            (time.perf_counter() - started) * 1000.0, 3
                        ),
                        "ts_ms": run_ts_ms(),
                    },
                )
            )

        evidence_records = (
            [context["evidence"]] if isinstance(context.get("evidence"), dict) else []
        )
        return {"prompt": context["prompt"], "evidence_records": evidence_records}
    except Exception as exc:
        logger.warning("FastAnswer 实时汇率工具预检失败: %s", exc)
        context = _build_exchange_realtime_context(
            query=state.user_query or "",
            base=base,
            target=target,
            envelope={"status": "failed", "error": str(exc)},
        )
        return {"prompt": context["prompt"], "evidence_records": []}
