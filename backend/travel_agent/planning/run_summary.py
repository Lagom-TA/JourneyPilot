"""规划 Run 状态摘要。"""

from __future__ import annotations

from typing import Any
from typing import Dict


def build_trip_run_state_summary(state: Any) -> Dict[str, Any]:
    """生成 TripRunState 的可写入追踪的最新状态投影。"""
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

    workspace = data.get("trip_workspace")
    packets = data.get("research_packets") or {}
    fact_store = data.get("fact_store_snapshot") or {}
    source_records = (
        fact_store.get("source_records") if isinstance(fact_store, dict) else []
    )
    identity = data.get("controlled_trip_identity") or {}
    identity_ready = isinstance(identity, dict) and bool(
        identity.get("destinations") and identity.get("start_date") and identity.get("end_date")
    )
    summary = {
        "task_type": task_type,
        "has_workspace": bool(workspace),
        "research_packet_count": len(packets),
        "source_record_count": len(source_records or []),
        "map_ready": bool(data.get("map_projection")),
        "synthesis_mode": data.get("synthesis_mode"),
        "route_decision": data.get("route_decision") or None,
        "identity_locked": identity_ready,
    }
    return summary
