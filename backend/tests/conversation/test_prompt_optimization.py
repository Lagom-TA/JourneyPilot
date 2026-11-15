"""提示词润色：保留本次表达，并区分可选历史参考的来源。"""

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
async def test_historical_preferences_precede_current_input_as_background():
    reply = "帮我规划杭州两天的旅行，不安排爬山。"
    llm = _FastLLM(reply)
    result = await optimize_travel_prompt(
        "杭州两天，不安排爬山",
        _router(llm),
        inferred_preferences="旅行风格：偏好慢节奏，喜欢爬山",
    )

    assert result == {"success": True, "optimized_prompt": reply, "error_message": None}
    assert llm.messages[1]["content"] == (
        "历史画像推测的偏好（仅供参考）：\n旅行风格：偏好慢节奏，喜欢爬山\n\n"
        "本次用户输入：\n杭州两天，不安排爬山"
    )
    system_prompt = llm.messages[0]["content"]
    assert "旅行风格：偏好慢节奏" not in system_prompt
    assert "历史画像推测的偏好用于理解表达" in system_prompt
    assert "润色结果以本次输入的旅行想法和已确认条件为准" in system_prompt
    assert "未提供的信息保持未知" in system_prompt


@pytest.mark.asyncio
async def test_current_form_defaults_and_question_answer_keep_equal_standing():
    prompt = (
        "自然语言：杭州两天。\n"
        "本次已提交表单（含默认值）：同行2人。\n"
        "助手提问（q1）：希望清晨出发吗？\n"
        "旅行者回答：不，尽量晚些。"
    )
    llm = _FastLLM("杭州两天，同行2人。助手提问是否清晨出发，旅行者回答希望晚些出发。")
    result = await optimize_travel_prompt(prompt, _router(llm))

    assert result["optimized_prompt"] == llm.reply
    assert llm.messages[1]["content"] == prompt
    system_prompt = llm.messages[0]["content"]
    assert "已提交表单中的值（包括默认值）和问答同等考虑" in system_prompt
    assert "结合完整的一问一答理解回答" in system_prompt
    assert "保留提问和回答并区分助手提问与旅行者回答" in system_prompt


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
