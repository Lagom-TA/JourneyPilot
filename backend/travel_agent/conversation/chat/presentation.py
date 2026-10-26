from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from travel_agent.conversation.stream_text import StreamingStripper
from travel_agent.planning.trace import make_trace_event


@dataclass
class ChatPresentation:
    """SSE 流处理器的可变状态容器。

    由 generate_sse 创建, 跨 handler 共享状态。
    所有 handler 只通过 ctx 读写状态, 避免闭包变量散落。
    """

    message_id: str
    session_id: str
    mode: str
    use_deep_research: bool
    task_type: str = ""
    full_response: str = ""
    final_agent_name: str = ""
    final_step_name: str = ""
    streamed_nodes: Set[str] = field(default_factory=set)
    progress_nodes_emitted: Set[str] = field(default_factory=set)
    stripper: StreamingStripper = field(default_factory=StreamingStripper)
    thinking_steps: List[Dict[str, Any]] = field(default_factory=list)
    trace_run_id: str = ""
    trace_sequence: int = 0
    trace_events: List[Dict[str, Any]] = field(default_factory=list)
    approval_gate: Optional[Dict[str, Any]] = None
    context_report: Optional[Dict[str, Any]] = None
    trip_summary_card: Optional[Dict[str, Any]] = None
    delivery_bundle_id: Optional[str] = None
    delivery_manifest: Optional[Dict[str, Any]] = None

    def next_trace(
        self,
        *,
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
    ) -> Dict[str, Any]:
        """Create and remember a trace event SSE payload."""
        self.trace_sequence += 1
        event = make_trace_event(
            run_id=self.trace_run_id or self.message_id,
            sequence=self.trace_sequence,
            node=node,
            status=status,
            phase=phase,
            input_summary=input_summary,
            output_summary=output_summary,
            route_decision=route_decision,
            agent=agent,
            tool_calls=tool_calls,
            risk_flags=risk_flags,
            ts_ms=ts_ms,
            duration_ms=duration_ms,
        ).to_dict()
        self.trace_events.append(event)
        return {"type": "trace_event", "message_id": self.message_id, **event}


def _trace_event_payload(event: Dict[str, Any]) -> Dict[str, Any]:
    """Whitelist the trace event fields that are safe for durable run events."""
    allowed = {
        "schema_version",
        "event_id",
        "run_id",
        "sequence",
        "node",
        "phase",
        "status",
        "input_summary",
        "output_summary",
        "route_decision",
        "agent",
        "tool_calls",
        "risk_flags",
        "ts_ms",
        "duration_ms",
    }
    return {key: event.get(key) for key in allowed if key in event}
