"""以自然语言保存旅行需求和模型提出的研究任务。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import Field, field_validator

from travel_agent.planning.requirements.generation_contracts import PlanningGeneration
from travel_agent.schema import StrictModel


class ResearchPlan(StrictModel):
    summary: str = Field(min_length=1)
    destination_task: str = Field(min_length=1)
    transport_task: str = Field(min_length=1)
    accommodation_task: str = Field(min_length=1)
    itinerary_task: str = Field(min_length=1)

    @field_validator("summary", "destination_task", "transport_task", "accommodation_task", "itinerary_task")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("研究方案和任务说明不能为空")
        return value

    def tasks(self) -> dict[str, str]:
        return {
            "destination_researcher": self.destination_task,
            "transport_researcher": self.transport_task,
            "accommodation_researcher": self.accommodation_task,
            "itinerary_planner": self.itinerary_task,
        }


def initial_requirements(user_query: str) -> str:
    """入口原文就是需求文字的起点；保留原有换行和顺序。"""
    return user_query.strip()


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
    """收集新输入；较新的补充按时间顺序保留，交给模型整体理解。"""
    base = state.current_requirements or initial_requirements(state.user_query)
    # 理解问答只在首次整理时并入；之后的重跑以已保存的需求文字为基底，
    # 不重复追加。
    qa_lines = []
    qa_lines = [
        f"{item['question']}：{item['answer']}"
        for item in (state.understanding_qa or [])
        if f"{item['question']}：{item['answer']}" not in base
    ]
    amendments = [*state.pending_intent_amendments]
    if state.plan_gate_amendment is not None:
        amendments.append(state.plan_gate_amendment)
    seen = set(state.applied_intent_amendment_ids)
    additions = []
    for amendment in amendments:
        if amendment.command_id in seen:
            continue
        additions.append(amendment.content.strip())
        seen.add(amendment.command_id)
    text = "\n".join([base, *qa_lines, *(f"后续补充：{item}" for item in additions)]).strip()
    if not text:
        text = "根据已提供的旅行基础信息规划行程。"
    from travel_agent.planning.requirements.constraints.planning import (
        build_planning_constraint_pack,
    )

    generation = next_generation(state, text)
    return {
        "current_requirements": text,
        "planning_generation": generation,
        "constraint_pack": await build_planning_constraint_pack(state),
        "pending_intent_amendments": [],
        "plan_gate_amendment": None,
        "applied_intent_amendment_ids": [item.command_id for item in amendments],
        "research_plan": None,
        "research_plan_error": None,
        "plan_gate_decision": {"action": "preparing"},
        "intent_amendment_route": None,
        "intent_amendment_resume_node": None,
    }
