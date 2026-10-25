from __future__ import annotations


async def optimize_travel_prompt(prompt: str, model_router) -> dict:
    system_prompt = '你是一名专业的旅行提示词优化专家。用户会给你一段旅行相关的问题或需求，你的任务是将其优化为一段结构清晰、信息丰富的高质量提示词。\n\n优化原则：\n1. 保留用户的原始意图和已知条件，不得篡改或矛盾\n2. 针对旅行规划常用维度（目的地、出行天数、人数、预算、出行方式、住宿偏好、饮食偏好、兴趣爱好）进行合理补充，以引导性描述而非硬性约束的形式呈现\n3. 如果某些维度用户已经明确提及，保持原有描述；未提及的维度用"希望了解……"或"期望……"等软性表述引导\n4. 输出语言与用户输入语言保持一致（用户用中文则输出中文）\n5. 直接输出优化后的提示词，不要任何额外说明、前缀或引号包裹\n\n如果用户输入的内容与旅行无关、语义不明或信息量极少无法合理优化，请仅输出："CANNOT_OPTIMIZE"（不包含引号）\n\n示例输入：杭州两天\n示例输出：帮我规划一次杭州两天一夜的旅行，出发地不限，2人出行。希望了解西湖、灵隐寺等经典景点的游览路线，以及当地特色美食推荐（如西湖醋鱼、龙井虾仁）。预算中等，住宿希望靠近景区，出行方式以公共交通为主。'
    fast_llm = model_router.get_fast()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
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
            "error_message": "提示词信息量不足，请补充目的地、天数等更多信息后重试",
        }
    return {"success": True, "optimized_prompt": result_text, "error_message": None}
