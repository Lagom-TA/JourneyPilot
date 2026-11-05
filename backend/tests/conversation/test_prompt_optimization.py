"""提示词润色：只整理用户已有的内容，推理偏好作为可选的软性补充。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from travel_agent.conversation.prompt_optimization import (
    inferred_preferences_text,
    optimize_travel_prompt,
)


class _FastLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.messages: list[dict[str, str]] = []

    async def ainvoke(self, messages):
        self.messages = messages
        return self.reply


def _router(llm: _FastLLM):
    return SimpleNamespace(get_fast=lambda: llm)


@pytest.mark.asyncio
async def test_without_preferences_the_model_only_sees_the_user_text():
    llm = _FastLLM("帮我规划杭州两天的旅行。")
    result = await optimize_travel_prompt("杭州两天", _router(llm))
    assert result == {"success": True, "optimized_prompt": "帮我规划杭州两天的旅行。", "error_message": None}
    assert llm.messages[1]["content"] == "杭州两天"
    assert "杭州" not in llm.messages[0]["content"]


@pytest.mark.asyncio
async def test_inferred_preferences_are_offered_after_the_stable_system_prompt():
    llm = _FastLLM("帮我规划杭州两天的旅行，节奏通常偏慢。")
    await optimize_travel_prompt("杭州两天", _router(llm), inferred_preferences="旅行风格：偏好慢节奏")
    content = llm.messages[1]["content"]
    assert "旅行风格：偏好慢节奏" in content and content.endswith("杭州两天")
    assert "旅行风格" not in llm.messages[0]["content"]


@pytest.mark.asyncio
async def test_cannot_optimize_is_reported_as_insufficient_input():
    result = await optimize_travel_prompt("今天天气", _router(_FastLLM("CANNOT_OPTIMIZE")))
    assert result["success"] is False and result["optimized_prompt"] == ""


@pytest.mark.asyncio
async def test_reading_the_portrait_never_breaks_the_polish():
    class _Broken:
        async def get_user_profile(self, user_id):
            raise RuntimeError("db down")

    class _Profile:
        async def get_user_profile(self, user_id):
            return SimpleNamespace(auto_portrait="  家庭状况：带孩子出行  ")

    class _Empty:
        async def get_user_profile(self, user_id):
            return None

    assert await inferred_preferences_text(_Broken()) == ""
    assert await inferred_preferences_text(_Profile()) == "家庭状况：带孩子出行"
    assert await inferred_preferences_text(_Empty()) == ""
