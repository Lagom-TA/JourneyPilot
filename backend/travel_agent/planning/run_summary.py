"""Planning run summary."""

from __future__ import annotations

from travel_agent.runtime.run_contracts import TripRunStatus
from typing import Any
from typing import Dict
from typing import Optional


def build_trip_run_state_summary(state: Any) -> Dict[str, Any]:
    """Return a trace-safe latest-state projection for TripRunState."""
    if state is None:
        return {}
    if hasattr(state, "model_dump"):
        data = state.model_dump()
    elif isinstance(state, dict):
        data = state
    else:
        data = {}

    task_type = data.get("task_type")
    if hasattr(task_type, "value"):
        task_type = task_type.value

    pending_choice = data.get("pending_user_choice")
    workspace = data.get("trip_workspace_v2")
    packets = data.get("research_packets") or {}
    fact_store = data.get("fact_store_snapshot") or {}
    source_records = (
        fact_store.get("source_records") if isinstance(fact_store, dict) else []
    )
    summary = {
        "task_type": task_type,
        "has_itinerary": bool(workspace),
        "has_workspace_v2": bool(workspace),
        "research_packet_count": len(packets),
        "source_record_count": len(source_records or []),
        "pending_user_choice": bool(pending_choice),
        "map_ready": bool(data.get("map_projection")),
        "synthesis_mode": data.get("synthesis_mode"),
        "route_decision": data.get("route_decision") or None,
        "identity_locked": bool(data.get("controlled_trip_identity")),
    }
    return summary


def with_pending_choice_summary(
    summary: Any,
    *,
    pending: bool,
) -> Dict[str, Any]:
    """Return a copy of a trace-safe summary with the interaction flag corrected."""
    data = dict(summary) if isinstance(summary, dict) else {}
    data["pending_user_choice"] = bool(pending)
    return data


def mark_cancelled_pending_choice(value: Any) -> Optional[Dict[str, Any]]:
    """把当前决策保存为取消终态的只读审计快照。"""
    if not isinstance(value, dict) or not value:
        return None
    return {
        **value,
        "read_only": True,
        "terminal_status": TripRunStatus.CANCELLED.value,
    }
