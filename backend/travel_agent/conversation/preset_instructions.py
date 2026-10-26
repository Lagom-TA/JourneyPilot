"""使用配置的 fast 模型生成结构化旅行风格预设。"""


async def generate_preset_instructions(description: str) -> dict:
    system_prompt = """你是旅行风格预设创建助手。用户会描述他们想要的旅行风格或场景，你需要生成一份结构化的预设指令。

输出 JSON 格式：
{
  "name": "预设名称（简洁，2-6个字）",
  "description": "一句话描述（20字以内）",
  "instructions": "详细的行为指令（参考示例格式，包含 5-8 条具体原则）",
  "constraints": {
    "duration": "建议时长（如 3-5天）或 null",
    "budget": "预算档位（经济/中等/奢华）或 null",
    "pace": "行程节奏（紧凑/悠闲/弹性）或 null",
    "focus_areas": ["关注领域1", "关注领域2"],
    "output_style": "详细日程表"
  },
  "icon": "lucide图标名（如 compass, map, utensils, mountain, baby, crown, piggy-bank, camera, palette, music）",
  "category": "custom"
}

	指令格式示例：
	"你正在以「亲子慢游」模式为用户规划旅行。请遵循以下原则：
	1. 优先选择步行距离短、排队压力低、适合儿童休息的活动。
	2. 每天保留明确的午休或机动时间，避免连续高强度移动。
	3. 对门票预约、儿童年龄限制和安全注意事项给出可核验提醒。"

	只输出 JSON，不要其他文字。"""

    from travel_agent.bootstrap.registry import get_components

    components = get_components()
    fast_llm = components.model_router.get_fast()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": description},
    ]

    raw = await fast_llm.ainvoke(messages)
    result_text = (
        raw.strip()
        if isinstance(raw, str)
        else (getattr(raw, "content", None) or "").strip()
    )

    from travel_agent.utils.json_helpers import safe_parse_json

    result = safe_parse_json(result_text)
    if result is None:
        raise ValueError("无法从 LLM 响应中提取有效 JSON")

    return {"success": True, "data": result}
