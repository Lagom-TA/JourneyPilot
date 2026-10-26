from __future__ import annotations

import json
from typing import Any

from travel_agent.conversation.history import append_recent_history
from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.itinerary.draft import ItineraryCompositionDraft
from travel_agent.planning.itinerary.locations import (
    _reuse_located_places,
    locate_authored_composition,
)
from travel_agent.planning.itinerary.model_schema import _composition_response_schema
from travel_agent.planning.itinerary.parsing import _parse_exact_llm_composition
from travel_agent.planning.itinerary.prompts import _build_composition_prompt


async def _compose_draft(
    state: TravelAgentState,
    task_desc: str,
    llm: Any,
) -> ItineraryCompositionDraft:
    """生成行程草稿；JSON 解析或结构校验失败时带上错误重试一次。"""
    native_schema = bool(
        getattr(getattr(llm, "capabilities", None), "supports_json_schema", False)
    )
    prompt = _build_composition_prompt(
        state,
        task_desc,
        skeleton_only=True,
        strict_wire_schema=native_schema,
    )
    messages = [{"role": "system", "content": prompt.system}]
    append_recent_history(messages, state, limit=4)
    messages.append({"role": "user", "content": prompt.runtime})
    kwargs = {
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "itinerary_composition_draft",
                "strict": native_schema,
                "schema": _composition_response_schema(
                    state.recommendation_catalog,
                    skeleton_only=True,
                    strict_wire=native_schema,
                ),
            },
        },
        # 同一输入重复生成时保持排程稳定，便于定位结构错误。
        "temperature": 0,
    }
    previous = state.placement_skeleton
    for attempt in range(2):
        response = await llm.ainvoke(messages, **kwargs)
        content = response.content if hasattr(response, "content") else response
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        try:
            draft = _reuse_located_places(
                _parse_exact_llm_composition(content), previous
            )
        except ValueError as exc:
            if attempt:
                raise
            messages.extend(
                [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            "上一次输出无法解析为行程草稿结构。请修正下面的问题并重新输出完整 JSON 对象，"
                            "其余内容保持不变。"
                            f"问题：{exc}"
                        ),
                    },
                ]
            )
            continue
        return await locate_authored_composition(draft, state)
    raise AssertionError("composition attempt budget exhausted")
