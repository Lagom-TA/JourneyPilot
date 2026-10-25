"""Planning requirements approval."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from travel_agent.config.loader import get_settings
from travel_agent.planning.delivery.minimum_draft import seal_minimum_delivery_draft
from travel_agent.planning.invalidation import invalidation_update
from travel_agent.planning.nodes import (
    NODE_DISPATCHER,
    NODE_INTENT_AMENDMENT_ROUTER,
    NODE_PLAN_GATE,
    NODE_REQUEST_CONTRACT_NORMALIZER,
)
from travel_agent.planning.presentation import get_agent_display_name
from travel_agent.planning.requirements.request_contracts import (
    AmendmentImpact,
    IntentAmendment,
)
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.cancellation import RunCancelled

logger = logging.getLogger(__name__)


_MAX_PLAN_GATE_REVISIONS = 1


def _configurable_value(config: Optional[RunnableConfig], key: str) -> Any:
    if not isinstance(config, dict):
        return None
    configurable = config.get("configurable")
    if not isinstance(configurable, dict):
        return None
    return configurable.get(key)


def _is_plan_gate_enabled(config: Optional[RunnableConfig]) -> bool:
    request_value = _configurable_value(config, "plan_gate_enabled")
    if request_value is not None:
        return bool(request_value)
    return bool(get_settings().run_control.plan_gate_enabled)


def _assignment_task_text(value: Any) -> str:
    """规范化单个 agent 的任务全文（不截断）。"""
    if isinstance(value, dict):
        text = str(value.get("objective") or "")
    else:
        text = str(value or "")
    return " ".join(text.split())


def _serialize_plan_text(state: TravelAgentState) -> str:
    """把结构化执行计划序列化为规范化的 markdown 全文（后端单一数据源）。"""
    assignments = state.agent_assignments or {}
    lines: List[str] = []
    for index, group in enumerate(state.execution_plan or [], start=1):
        agents = [
            str(agent) for agent in (group if isinstance(group, list) else [group])
        ]
        agent_labels = "、".join(get_agent_display_name(agent) for agent in agents)
        lines.append(f"### 步骤 {index}：{agent_labels}")
        for agent in agents:
            task = _assignment_task_text(assignments.get(agent)) or "（待补充任务描述）"
            lines.append(f"- **{get_agent_display_name(agent)}**：{task}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _build_plan_gate_payload(state: TravelAgentState) -> Dict[str, Any]:
    steps: List[Dict[str, Any]] = []
    assignments = state.agent_assignments or {}
    for index, group in enumerate(state.execution_plan or [], start=1):
        agents = [
            str(agent) for agent in (group if isinstance(group, list) else [group])
        ]
        steps.append(
            {
                "step": index,
                "agents": agents,
                "tasks": {
                    agent: _assignment_task_text(assignments.get(agent))
                    for agent in agents
                },
            }
        )

    revision = int(state.plan_gate_revision_count or 0)
    limit_reached = revision >= _MAX_PLAN_GATE_REVISIONS
    constraint_pack = (
        state.constraint_pack if isinstance(state.constraint_pack, dict) else {}
    )
    hard_requirements = [
        {
            "requirement_id": str(item.get("constraint_id") or ""),
            "summary": str(item.get("public_summary") or ""),
        }
        for item in constraint_pack.get("hard_constraints") or []
        if isinstance(item, dict) and item.get("status") in (None, "active")
    ]
    preferences: List[Dict[str, str]] = []
    attention: List[Dict[str, str]] = []
    if state.intent_spec is not None:
        existing_summaries = {item["summary"] for item in hard_requirements}
        for item in state.intent_spec.active_items:
            row = {
                "requirement_id": item.intent_id,
                "summary": item.public_summary,
            }
            if item.strength.value == "hard":
                if row["summary"] not in existing_summaries:
                    hard_requirements.append(row)
                    existing_summaries.add(row["summary"])
            else:
                preferences.append(row)
        attention.extend(
            {
                "requirement_id": conflict.conflict_id,
                "summary": conflict.user_visible_summary,
            }
            for conflict in state.intent_spec.conflicts
        )
        attention.extend(
            {
                "requirement_id": clause.clause_id,
                "summary": f"暂未纳入：{clause.source_text}",
            }
            for clause in state.intent_spec.unresolved_clauses
        )
    return {
        "gate": "plan",
        "revision": revision,
        "revision_limit": _MAX_PLAN_GATE_REVISIONS,
        "revision_limit_reached": limit_reached,
        "plan": {
            "steps": steps,
        },
        "plan_text": _serialize_plan_text(state),
        "recognized_requirements": {
            "hard": hard_requirements,
            "preferences": preferences,
            "attention": attention,
        },
        "decision_options": ["approve", "cancel"]
        if limit_reached
        else ["approve", "edit", "supplement", "cancel"],
    }


def _validate_plan_gate_contract(state: TravelAgentState) -> None:
    contract = state.request_contract
    plan = state.capability_plan
    draft = state.minimum_delivery_draft
    brief = state.research_brief
    if contract is None or brief is None or plan is None or draft is None:
        raise RuntimeError(
            "plan gate requires request, research, capability and minimum-delivery contracts"
        )
    if contract.has_blocking_conflicts:
        raise RuntimeError("request contract contains a blocking intent conflict")
    if contract.has_unresolved_material_clauses:
        raise RuntimeError("request contract contains an unresolved material clause")
    hard_ids = {
        item.intent_id
        for item in contract.intent_spec.active_items
        if item.strength.value == "hard"
    }
    owned_ids = {
        intent_id
        for assignment in plan.assignments.values()
        for intent_id in assignment.must_cover_intent_ids
    }
    if hard_ids - owned_ids:
        raise RuntimeError("active hard intent lacks capability ownership")
    objective_intents = {
        intent_id
        for objective in brief.domain_objectives
        for intent_id in [
            *objective.must_cover_intent_ids,
            *objective.optional_intent_ids,
        ]
    }
    research_ids = {
        item.intent_id
        for item in contract.intent_spec.active_items
        if "research" in item.impact_stages
    }
    if research_ids - objective_intents:
        raise RuntimeError("research-affecting intent lacks a research objective")
    if draft.planning_generation_id != contract.generation_id:
        raise RuntimeError("minimum delivery draft belongs to another generation")
    if (
        draft.intent_spec_revision != contract.intent_spec.revision
        or draft.intent_spec_hash != contract.intent_spec.content_hash
    ):
        raise RuntimeError("minimum delivery draft belongs to another intent contract")
    if plan.generation_id != contract.generation_id:
        raise RuntimeError("capability plan belongs to another generation")
    if plan.intent_spec_revision != contract.intent_spec.revision:
        raise RuntimeError("capability plan uses another intent revision")


def _projection_only_amendment(content: str) -> bool:
    lowered = content.lower()
    presentation = ("报告", "输出", "措辞", "简洁", "格式", "排版", "summary", "format")
    material = (
        "不要",
        "安排",
        "每天",
        "景点",
        "餐",
        "酒店",
        "交通",
        "预算",
        "must",
        "avoid",
    )
    return any(token in lowered for token in presentation) and not any(
        token in lowered for token in material
    )


async def plan_gate_node(
    state: TravelAgentState, config: Optional[RunnableConfig] = None
) -> Dict[str, Any]:
    """Block after planning and before worker fan-out until the user decides."""
    constraint_pack = (
        state.constraint_pack if isinstance(state.constraint_pack, dict) else {}
    )
    pack_meta = (
        constraint_pack.get("pack_meta")
        if isinstance(constraint_pack.get("pack_meta"), dict)
        else {}
    )
    if pack_meta.get("hard_constraint_contract_complete") is False:
        unsupported = pack_meta.get("unsupported_hard_constraint_ids") or []
        raise RuntimeError(
            "hard constraint contract is incomplete: "
            + ", ".join(str(item) for item in unsupported)
        )
    _validate_plan_gate_contract(state)

    if not _is_plan_gate_enabled(config):
        raise RuntimeError("controlled planning requires an enabled approval gate")

    if (state.plan_gate_decision or {}).get("action") == "projection_amendment_pending":
        return {
            "plan_gate_decision": {
                "action": "approve",
                "revision": state.plan_gate_revision_count,
            },
            **seal_minimum_delivery_draft(state),
        }

    while True:
        decision = interrupt(_build_plan_gate_payload(state))
        if not isinstance(decision, dict):
            logger.info(
                "plan_gate: non-object decision rejected; waiting for explicit approve/cancel"
            )
            continue

        action = str(decision.get("action") or "").lower()
        revision_count = int(state.plan_gate_revision_count or 0)
        limit_reached = revision_count >= _MAX_PLAN_GATE_REVISIONS

        if action == "cancel":
            raise RunCancelled(state.run_id, NODE_PLAN_GATE)

        if action not in {"approve", "edit", "supplement"}:
            logger.info("plan_gate: unsupported action %s rejected", action)
            continue

        if action in ("edit", "supplement"):
            if limit_reached:
                logger.info(
                    "plan_gate: 修改额度已用满，忽略 %s，重新等待 approve/cancel",
                    action,
                )
                continue
            content = " ".join(str(decision.get("content") or "").split())[:2000]

            if not content:
                logger.info("plan_gate: %s 缺少 content，重新 interrupt", action)
                continue
            amendment = IntentAmendment(
                command_id=f"plan_gate_{state.run_id}_{revision_count + 1}",
                category=action,
                content=content,
                source_kind="plan_gate_amendment",
                impact=(
                    AmendmentImpact.PROJECTION_ONLY
                    if _projection_only_amendment(content)
                    else AmendmentImpact.RESEARCH_AFFECTING
                ),
            )
            return {
                "plan_gate_amendment": amendment,
                "plan_gate_decision": {
                    "action": "amendment",
                    "revision": revision_count + 1,
                },
                "plan_gate_revision_count": revision_count + 1,
                **invalidation_update(amendment.impact),
            }

        approve_content = str(decision.get("content") or "").strip()[:2000]
        if approve_content:
            if limit_reached:
                logger.info(
                    "plan_gate: 修改额度已用满，忽略 approve content，重新等待 approve/cancel"
                )
                continue
            projection_only = _projection_only_amendment(approve_content)
            amendment = IntentAmendment(
                command_id=f"plan_gate_{state.run_id}_{revision_count + 1}",
                category=(
                    "projection_only_approve" if projection_only else "approve_content"
                ),
                content=approve_content,
                source_kind="plan_gate_amendment",
                impact=(
                    AmendmentImpact.PROJECTION_ONLY
                    if projection_only
                    else AmendmentImpact.RESEARCH_AFFECTING
                ),
            )
            return {
                "plan_gate_amendment": amendment,
                "plan_gate_decision": {
                    "action": (
                        "projection_amendment_pending"
                        if projection_only
                        else "amendment"
                    ),
                    "revision": revision_count + 1,
                },
                "plan_gate_revision_count": revision_count + 1,
                **invalidation_update(
                    AmendmentImpact.PROJECTION_ONLY
                    if projection_only
                    else AmendmentImpact.RESEARCH_AFFECTING
                ),
            }
        return {
            "plan_gate_decision": {
                "action": "approve",
                "revision": revision_count,
            },
            **seal_minimum_delivery_draft(state),
        }


def route_after_plan_gate(state: TravelAgentState) -> str:
    if state.pending_intent_amendments:
        return NODE_INTENT_AMENDMENT_ROUTER
    decision = state.plan_gate_decision or {}
    if decision.get("action") in ("amendment", "projection_amendment_pending"):
        return NODE_REQUEST_CONTRACT_NORMALIZER
    return NODE_DISPATCHER
