from __future__ import annotations

import logging

from travel_agent.conversation.chat.preparation import check_input_guard
from travel_agent.runtime.local_identity import LOCAL_USER_ID

logger = logging.getLogger(__name__)


async def prepare_prompt_optimization(prompt: str) -> tuple[str, dict | None]:
    """校验输入后返回待优化文本，或返回可直接展示的拒绝结果。"""
    prompt = prompt.strip()
    if len(prompt) < 4:
        return prompt, {
            "success": False,
            "optimized_prompt": "",
            "error_message": "描述太短，请补充更多信息后重试",
        }

    guard_result = await check_input_guard(prompt)
    if guard_result.is_blocked:
        logger.warning("InputGuard blocked optimize-prompt: %s", guard_result.reason)
        return prompt, {
            "success": False,
            "optimized_prompt": "",
            "error_message": guard_result.blocked_reply
            or "请求未通过安全检查，请修改后重试",
        }
    return prompt, None


_SYSTEM_PROMPT = """你是旅行提示词的润色助手。把用户本次的旅行想法改写成自然通顺、可以直接发给旅行规划助手的话。

- 保留本次输入的原意、已提供的条件（目的地、天数、人数、预算、偏好等）及确定程度，未提供的信息保持未知。
- 本次输入中的自然语言、已提交表单中的值（包括默认值）和问答同等考虑；结合完整的一问一答理解回答，保留提问和回答并区分助手提问与旅行者回答。
- 历史画像推测的偏好用于理解表达；润色结果以本次输入的旅行想法和已确认条件为准。
- 用与用户输入一致的语言写成自然、简洁、连贯的文字，只输出改写后的文本。
- 输入与旅行无关、语义不明或信息太少无法改写时，只输出 CANNOT_OPTIMIZE。"""


async def inferred_preferences_text(user_profile_memory) -> str:
    """系统从历史对话推理出的画像；读取失败或没有画像时返回空串，不影响润色本身。"""
    try:
        profile = await user_profile_memory.get_user_profile(LOCAL_USER_ID)
    except Exception as exc:
        logger.warning("读取推理偏好失败，按无偏好润色: %s", exc)
        return ""
    return (profile.auto_portrait or "").strip() if profile else ""


def _user_message(prompt: str, inferred_preferences: str) -> str:
    if not inferred_preferences:
        return prompt
    return f"历史画像推测的偏好（仅供参考）：\n{inferred_preferences}\n\n本次用户输入：\n{prompt}"


async def optimize_travel_prompt(
    prompt: str, model_router, *, inferred_preferences: str = ""
) -> dict:
    """润色提示词；入口没有 Run，这次调用不写 ``run_llm_calls``（run_id 是外键）。"""
    fast_llm = model_router.get_fast()
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _user_message(prompt, inferred_preferences.strip())},
    ]
    raw = await fast_llm.ainvoke(messages)
    if isinstance(raw, str):
        result_text = raw.strip()
    else:
        result_text = (getattr(raw, "content", None) or "").strip()
    if not result_text or result_text == "CANNOT_OPTIMIZE":
        return {
            "success": False,
            "optimized_prompt": "",
            "error_message": "描述信息量不足，请补充目的地、天数等更多信息后重试",
        }
    return {"success": True, "optimized_prompt": result_text, "error_message": None}
