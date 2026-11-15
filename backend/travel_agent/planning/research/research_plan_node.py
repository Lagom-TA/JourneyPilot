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
                "你是旅行研究协调员。根据旅行基础信息和整理后的旅行要求，分别写给旅行者看的研究方案和给研究角色的指引。"
                "summary 面向旅行者，通常用 3–4 条简短的 Markdown 无序列表，每条说明一个具体的研究或安排方向；"
                "围绕这趟旅行的特点合并表达，信息较少时可以少写，不为凑数添加通用方向。"
                "自然融入最影响安排的要求，上限、禁忌或条件保留关键含义和数值；不要把所有要求堆成一段，"
                "也不要重复页面上已有的日期、人数等基础信息。"
                "用直接、积极、好懂的行动表述；不写泛泛的免责声明、推脱或‘视情况’‘以实际为准’等套话。"
                "尚未核实的事实说明需要查询什么，不将未知信息写成已知，不编造结果或作无法保证的承诺。"
                "agent_guidance 给研究和行程角色，提炼与研究、安排有关的重点与限制；"
                "它与完整旅行要求一起使用，不必重复列举每项要求，不得曲解、强化、弱化或新增用户要求。"
                "两份内容都只依据旅行理解，忠实区分明确要求与偏好，保留用户表达中的未知和条件；"
                "可指出研究重点，但不擅自排除必要研究，不规定查询方法、工具、候选数量，"
                "不承诺研究次序、角色分工或并行执行，除非旅行者自己明确提出。"
                "只返回一个 JSON 对象：{\"summary\": \"面向旅行者的简短方案\", \"agent_guidance\": \"给研究角色的内部指引\"}。"
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
        if plan.agent_guidance is None:
            raise ValueError("研究方案缺少内部指引")
    except (TimeoutError, OpenAIError, TypeError, ValueError, ValidationError, RuntimeError) as exc:
        logger.warning("研究方案生成失败: %s", exc)
        return {"research_plan": None, "research_plan_error": {"code": "research_plan_unavailable", "detail": str(exc)[:300]}}
    return {"research_plan": plan, "research_plan_error": None}
