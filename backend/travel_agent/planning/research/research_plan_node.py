"""根据旅行理解生成研究设想。"""

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
                "你是旅行研究协调员。根据提供的旅行理解，为旅行者提出本次旅行的研究与安排设想。"
                "用简洁、自然、规范的语言说明大致会关注什么、如何规划，点出影响旅行意图的关键要求；"
                "不要罗列角色分工或把需求拆成逐条合同。"
                "忠实体现旅行理解中的明确要求，重点说明影响安排的关键点；"
                "没有说明的条件保持未知，不要自行添加要求。"
                "设想只提供方向，不主动规定查询方法、工具、候选数量或研究范围；"
                "如果旅行者明确提出这些要求，应按原意体现，不受前述限制。"
                "不要承诺具体研究次序或并行执行。"
                "只返回一个 JSON 对象：{\"summary\": \"面向旅行者的研究与安排设想\"}。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "旅行基础信息": state.controlled_trip_identity,
                    "整理后的旅行要求": state.current_requirements,
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
        plan = ResearchPlan.model_validate(parsed)
    except (TimeoutError, OpenAIError, TypeError, ValueError, ValidationError, RuntimeError) as exc:
        logger.warning("研究方案生成失败: %s", exc)
        return {"research_plan": None, "research_plan_error": {"code": "research_plan_unavailable", "detail": str(exc)[:300]}}
    return {"research_plan": plan, "research_plan_error": None}
