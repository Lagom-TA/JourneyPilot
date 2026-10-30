"""规划阶段的失效更新。"""

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
        "research_plan_error": None,
        "research_plan_retry_count": 0,
        "research_operation_manifest": None,
        "research_operation_approval": None,
        "research_operation_limitations": [],
        "is_completed": False,
    }


def invalidation_update(impact: AmendmentImpact) -> Dict[str, Any]:
    if impact is AmendmentImpact.PROJECTION_ONLY:
        # 展示性修改也会推进 Intent revision。旧的 Brief/查询/能力计划与
        # 未重新批准的 Draft 都属于上一版合同，不能原样留到下一次状态校验。
        return {
            **_projection_invalidation(),
            "semantic_receipt": None,
            "semantic_candidate_hash": None,
            "research_brief": None,
            "capability_plan": None,
            "research_query_plan": None,
            "minimum_delivery_draft": None,
            "run_deadline": None,
            "run_budget": None,
        }
    composition = {
        **workspace_acceptance_invalidation(),
        "semantic_receipt": None,
        "semantic_candidate_hash": None,
        "placement_skeleton": None,
        "composition_mutations": [],
        "trip_workspace_v2": None,
        "composition_failure_context": None,
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
    }


def generation_packet_key(worker_key: str, generation_id: str) -> str:
    return f"{worker_key}@{generation_id}"
