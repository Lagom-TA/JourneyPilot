"""根据旅行基础信息和自然语言需求生成研究方案。"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict

from openai import OpenAIError
from pydantic import ValidationError

from travel_agent.llm.router import get_model_router
from travel_agent.llm.task_routing import TaskKind, llm_for_task
from travel_agent.planning.requirements.natural_language import ResearchPlan
from travel_agent.planning.state import TravelAgentState
from travel_agent.utils.json_helpers import safe_parse_json

logger = logging.getLogger(__name__)


async def research_plan_generator_node(state: TravelAgentState) -> Dict[str, Any]:
    if state.planning_generation is None:
        raise ValueError("研究方案需要当前规划版本")
    prompt = [
        {
            "role": "system",
            "content": (
                "你是旅行研究协调员。根据基础信息、用户原话与追问回答，为本次旅行写简短具体的研究和安排行动方案。"
                "理解后续补充对先前想法的修改，以较新的表达为准；不要把用户原话拆成逐条合同，也不要要求用户确认原话。"
                "为目的地、交通、住宿、行程组合分别写清有关任务，任务应可直接交给对应研究员。"
                "用中文写简洁具体的方案。只返回 JSON 对象，字段为 summary、destination_task、transport_task、accommodation_task、itinerary_task。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "旅行基础信息": state.controlled_trip_identity,
                    "用户需求与回答": state.current_requirements,
                    "长期偏好与记忆": [
                        {"类别": item.get("category"), "内容": item.get("value"), "强度": item.get("type")}
                        for item in state.constraint_pack.get("constraints", [])
                        if item.get("status") == "active"
                        and item.get("visibility") != "internal_only"
                    ],
                    "其他背景": state.preset_context,
                },
                ensure_ascii=False, default=str,
            ),
        },
    ]
    try:
        llm = llm_for_task(get_model_router(), TaskKind.PLANNING)
        response = await asyncio.wait_for(
            llm.ainvoke(prompt, response_format={"type": "json_object"}, temperature=0),
            timeout=120,
        )
        content = getattr(response, "content", response)
        parsed = content if isinstance(content, dict) else safe_parse_json(content, strip_think_tags=True)
        if isinstance(parsed, dict) and isinstance(parsed.get("plan"), dict):
            parsed = parsed["plan"]
        if isinstance(parsed, dict):
            parsed = {key: parsed[key] for key in ResearchPlan.model_fields if key in parsed}
        plan = ResearchPlan.model_validate(parsed)
    except (TimeoutError, OpenAIError, TypeError, ValueError, ValidationError, RuntimeError) as exc:
        logger.warning("研究方案生成失败: %s", exc)
        return {"research_plan": None, "research_plan_error": {"code": "research_plan_unavailable", "detail": str(exc)[:300]}}
    return {"research_plan": plan, "research_plan_error": None}
