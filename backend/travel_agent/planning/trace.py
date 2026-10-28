"""规划工作流追踪事件。"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

TRACE_SCHEMA_VERSION = "workflow_trace_event.v1"


NODE_PHASES: Dict[str, str] = {
    "scope_clarifier": "scope",
    "request_contract_normalizer": "scope",
    "research_brief_builder": "scope",
    "intent_amendment_router": "planning",
    "minimum_delivery_draft_builder": "planning",
    "destination_geo_resolver": "planning",
    "weather_context_builder": "planning",
    "trip_summary_card_brief": "planning",
    "planner": "planning",
    "plan_gate": "planning",
    "dispatcher": "planning",
    "destination_researcher": "research",
    "transport_researcher": "research",
    "accommodation_researcher": "research",
    "itinerary_planner": "research",
    "budget_estimate": "delivery",
    "delivery_projector": "delivery",
    "delivery_finalizer": "delivery",
    "fast_answer_agent": "synthesis",
    "workflow": "postprocess",
}


def infer_trace_phase(node: str, fallback: str = "postprocess") -> str:
    """返回工作流节点对应的稳定 JourneyPilot 阶段名。"""
    return NODE_PHASES.get(str(node or ""), fallback)


def compact_summary(value: Any, *, limit: int = 180) -> str:
    """生成单行摘要，不暴露原始载荷。"""
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


@dataclass
class WorkflowTraceEvent:
    """供 SSE 与调试时间线使用的轻量 v1 追踪事件。"""

    run_id: str
    sequence: int
    node: str
    phase: str
    status: str
    event_id: str = field(default_factory=lambda: f"tr_{uuid.uuid4().hex[:12]}")
    schema_version: str = TRACE_SCHEMA_VERSION
    input_summary: Optional[str] = None
    output_summary: Optional[str] = None
    route_decision: Optional[str] = None
    agent: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    risk_flags: List[str] = field(default_factory=list)
    ts_ms: Optional[float] = None
    duration_ms: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "node": self.node,
            "phase": self.phase,
            "status": self.status,
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "route_decision": self.route_decision,
            "agent": self.agent,
            "tool_calls": self.tool_calls,
            "risk_flags": self.risk_flags,
            "ts_ms": self.ts_ms,
            "duration_ms": self.duration_ms,
        }


def make_trace_event(
    *,
    run_id: str,
    sequence: int,
    node: str,
    status: str = "completed",
    phase: Optional[str] = None,
    input_summary: Any = None,
    output_summary: Any = None,
    route_decision: Optional[str] = None,
    agent: Optional[str] = None,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    risk_flags: Optional[List[str]] = None,
    ts_ms: Optional[float] = None,
    duration_ms: Optional[float] = None,
) -> WorkflowTraceEvent:
    return WorkflowTraceEvent(
        run_id=run_id,
        sequence=sequence,
        node=node,
        phase=phase or infer_trace_phase(node),
        status=status,
        input_summary=compact_summary(input_summary) or None,
        output_summary=compact_summary(output_summary) or None,
        route_decision=route_decision,
        agent=agent,
        tool_calls=tool_calls or [],
        risk_flags=risk_flags or [],
        ts_ms=ts_ms,
        duration_ms=duration_ms,
    )


def summarize_state_update(node: str, state_update: Dict[str, Any]) -> Dict[str, Any]:
    """从 LangGraph 状态更新帧提取可写入追踪的摘要。"""
    if not isinstance(state_update, dict):
        return {"output_summary": "node completed"}

    route_decision = None
    risk_flags: List[str] = []
    parts: List[str] = []

    if state_update.get("next_agent"):
        route_decision = str(state_update.get("next_agent"))
        parts.append(f"route={route_decision}")
    if state_update.get("execution_plan"):
        plan = state_update.get("execution_plan") or []
        parts.append(f"plan_steps={len(plan)}")
    if state_update.get("constraint_pack"):
        pack = state_update.get("constraint_pack") or {}
        if isinstance(pack, dict):
            parts.append(f"constraints={len(pack.get('constraints') or [])}")
    if state_update.get("agent_status"):
        parts.append(f"agent_status={len(state_update.get('agent_status') or {})}")
    if state_update.get("research_packets"):
        parts.append(
            f"research_packets={len(state_update.get('research_packets') or {})}"
        )
    if state_update.get("map_projection"):
        parts.append("map_projection=ready")
    if state_update.get("pending_user_choice"):
        route_decision = "HALT"
        parts.append("pending_user_choice=true")

    return {
        "output_summary": ", ".join(parts) or "node completed",
        "route_decision": route_decision,
        "risk_flags": risk_flags,
    }
