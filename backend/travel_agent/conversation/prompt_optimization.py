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


_SYSTEM_PROMPT = """你是旅行提示词的润色助手。用户会给你一段旅行想法，你把它改写成一段自然通顺、可以直接发给旅行规划助手的话。

- 保留用户的原意和已经说出的条件（目的地、天数、人数、预算、偏好等），不改变含义、不新增、不矛盾。用户没提到的维度不要补充。
- 写成一两句连贯的话，不要写成字段清单。
- 输入里如果附有「系统推理的偏好」，只在它与用户这句话不冲突、与这次旅行相关时，用「希望……」「通常偏好……」这类软性说法简短并入。它只是推断，不当作硬性要求；不相关的不要硬塞，也不要说明这些偏好从何而来。
- 输出语言与用户输入一致，只输出改写后的那段话，不加说明、前缀或引号。
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
    return f"系统推理的偏好（仅供参考）：\n{inferred_preferences}\n\n用户输入：\n{prompt}"


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
