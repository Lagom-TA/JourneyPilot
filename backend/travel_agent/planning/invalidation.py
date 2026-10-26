"""Planning invalidation."""

from __future__ import annotations

from travel_agent.planning.requirements.request_contracts import AmendmentImpact
from typing import Any
from typing import Dict


def workspace_acceptance_invalidation() -> Dict[str, Any]:
    return _projection_invalidation()


def _projection_invalidation() -> Dict[str, Any]:
    return {
        "report_projection": None,
        "map_projection": None,
        "source_index_projection": None,
        "delivery_bundle": None,
        "delivery_failure": None,
        "delivery_persisted": False,
        "is_completed": False,
    }


def invalidation_update(impact: AmendmentImpact) -> Dict[str, Any]:
    if impact is AmendmentImpact.PROJECTION_ONLY:
        return _projection_invalidation()
    composition = {
        **workspace_acceptance_invalidation(),
        "placement_skeleton": None,
        "composition_mutations": [],
        "trip_workspace_v2": None,
        "composition_failure_context": None,
        "placement_skeleton_failure_context": None,
        "local_connector_gaps": [],
    }
    if impact is AmendmentImpact.COMPOSITION_AFFECTING:
        return composition
    return {
        **composition,
        "recommendation_catalog": None,
        "research_brief": None,
        "capability_plan": None,
        "research_query_plan": None,
        "execution_plan": [],
        "agent_assignments": {},
        "current_plan_step": 0,
        "agent_status": {},
        "minimum_delivery_draft": None,
        "run_deadline": None,
        "run_budget": None,
        "provider_evidence_outcomes": {},
        "weather_impacts": {},
        "unlocatable_authored_places": [],
    }


def generation_packet_key(worker_key: str, generation_id: str) -> str:
    return f"{worker_key}@{generation_id}"


def packet_key_generation(key: str) -> str | None:
    if "@" not in key:
        return None
    return key.rsplit("@", 1)[1]
