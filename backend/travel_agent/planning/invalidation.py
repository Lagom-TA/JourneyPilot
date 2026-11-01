"""规划版本发生变化时失效下游结果。"""

from __future__ import annotations

from typing import Any, Dict

def workspace_acceptance_invalidation() -> Dict[str, Any]:
    return {
        "report_projection": None,
        "map_projection": None,
        "source_index_projection": None,
        "delivery_bundle": None,
        "delivery_failure": None,
        "delivery_persisted": False,
        "is_completed": False,
    }


def invalidation_update() -> Dict[str, Any]:
    return {
        **workspace_acceptance_invalidation(),
        "research_plan": None,
        "research_plan_error": None,
        "recommendation_catalog": None,
        "execution_plan": [],
        "agent_assignments": {},
        "current_plan_step": 0,
        "agent_status": {},
        "minimum_delivery_draft": None,
        "provider_evidence_outcomes": {},
        "weather_impacts": {},
        "provider_reference_services": [],
        "placement_skeleton": None,
        "composition_mutations": [],
        "trip_workspace_v2": None,
        "composition_failure_context": None,
        "local_connector_gaps": [],
    }


def generation_packet_key(worker_key: str, generation_id: str) -> str:
    return f"{worker_key}@{generation_id}"
