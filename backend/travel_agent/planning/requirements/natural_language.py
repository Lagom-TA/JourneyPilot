"""以自然语言保存旅行需求和模型提出的研究设想。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import Field, field_validator

from travel_agent.planning.requirements.generation_contracts import PlanningGeneration
from travel_agent.planning.requirements.identity_contracts import ControlledTripIdentity
from travel_agent.schema import StrictModel


class ResearchPlan(StrictModel):
    summary: str = Field(min_length=1)

    @field_validator("summary")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("研究设想不能为空")
        return value


def next_generation(state: Any, requirements: str) -> PlanningGeneration:
    previous = state.planning_generation
    revision = previous.revision + 1 if previous else 1
    material = json.dumps(
        {"run_id": state.run_id, "revision": revision, "identity": state.controlled_trip_identity, "requirements": requirements},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    )
    return PlanningGeneration(
        generation_id="generation_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24],
        revision=revision,
    )


async def prepare_requirements_node(state: Any) -> dict[str, Any]:
    """使用理解结果生成规划版本，并标记已整理的补充。"""
    text = state.current_requirements.strip()
    if not text:
        raise ValueError("生成研究方案前需要整理后的旅行要求")
    identity = ControlledTripIdentity.model_validate(state.controlled_trip_identity)
    if not identity.destinations or identity.start_date is None or identity.end_date is None:
        raise ValueError("目的地或旅行日期尚未核实，暂时无法生成按天安排。")
    amendments = [*state.pending_intent_amendments]
    if state.plan_gate_amendment is not None:
        amendments.append(state.plan_gate_amendment)
    generation = next_generation(state, text)
    return {
        "planning_generation": generation,
        "pending_intent_amendments": [],
        "plan_gate_amendment": None,
        "applied_intent_amendment_ids": [item.command_id for item in amendments],
        "research_plan": None,
        "research_plan_error": None,
        "plan_gate_decision": {"action": "preparing"},
        "intent_amendment_route": None,
        "intent_amendment_resume_node": None,
    }
