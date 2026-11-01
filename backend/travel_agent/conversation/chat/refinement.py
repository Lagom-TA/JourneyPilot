"""结合已交付旅行理解后续输入。"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

from travel_agent.llm.router import get_model_router
from travel_agent.utils.json_helpers import safe_parse_json


class RefinementDecision(BaseModel):
    action: Literal["answer", "revise", "replan", "clarify"]
    response: str = Field(default="")


async def understand_followup(text, identity, bundle) -> RefinementDecision:
    """让模型结合当前行程判断回答、局部调整或重新规划。"""
    itinerary = bundle.workspace.itinerary.model_dump(mode="json", exclude_none=True)
    messages = [
        {
            "role": "system",
            "content": (
                "你负责理解用户对当前旅行的后续输入。结合基础信息、现有日程和用户需求判断："
                "询问或解释用 answer；明确局部调整用 revise；目的地、日期、出发地、同行人等"
                "基础条件改变需要重新理解和研究时用 replan；影响旅行范围且无法判断时用 clarify。"
                "只有 clarify 需要在 response 中写一句具体问题，其余 response 留空。"
                "只输出 JSON：{\"action\":\"answer|revise|replan|clarify\",\"response\":\"\"}。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {"基础信息": identity, "当前需求": bundle.workspace.requirements,
                 "当前行程": itinerary, "用户新输入": text},
                ensure_ascii=False,
                default=str,
            ),
        },
    ]
    raw = await get_model_router().get_primary().ainvoke(
        messages, response_format={"type": "json_object"}
    )
    parsed = safe_parse_json(raw, strip_think_tags=True)
    return RefinementDecision.model_validate(parsed)


def answer_context(identity, bundle) -> str:
    return json.dumps(
        {"基础信息": identity, "用户需求": bundle.workspace.requirements,
         "当前行程": bundle.workspace.itinerary.model_dump(mode="json", exclude_none=True)},
        ensure_ascii=False,
        default=str,
    )
