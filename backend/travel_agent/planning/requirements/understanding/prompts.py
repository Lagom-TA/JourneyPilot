"""理解代理的提示词与初始上下文。"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from travel_agent.planning.requirements.constraints.presentation import (
    format_constraint_pack_for_prompt,
)


def understanding_system_prompt() -> str:
    return (
        "你是旅行规划的需求理解者。用户刚提出一个旅行想法，你在正式研究前整体理解它："
        "可以用工具查询真实信息（网络资料、真实地点、汇率等），先查后问——能查到的不要问用户，"
        "已有信息绝不重复询问；后续补充改变先前基础条件时，以用户最新要求为准，保留仍适用的信息。"
        "\n\n"
        "工作方式："
        "\n- 先通读用户的原文、表单基础信息、长期偏好和历史问答，识别真正影响方案的缺口与取舍。"
        "\n- 需要外部事实（地点是否存在、位置关系、大致情况）就用工具查，不要凭空假设。"
        "\n- 只有值得用户决定的问题才问：每题二至六个具体选项，允许自由回答；一次只问确实必要的少数问题，"
        "没有值得问的就直接给出结果。不要为了提问而提问，也不要把用户已经表达过的信息再问一遍。"
        "\n- 信息充分后直接进入 ready，不需要任何确认或客套。"
        "\n\n"
        "输出契约（只输出一个 JSON 对象，不要多余文字）："
        "\n- 需要用户回答时：{\"action\": \"ask\", \"questions\": [{\"id\": \"简短英文标识\", "
        "\"question\": \"问题\", \"kind\": \"single 或 multiple\", \"options\": [{\"id\": \"简短英文标识\", \"label\": \"选项\"}]}]}"
        "\n- 信息充分时：{\"action\": \"ready\", \"trip_identity\": {…}}"
        "\n\n"
        "trip_identity 的形状（地点必须是工具查到的真实记录，原样复制工具返回的地点字段，不要编造坐标或 ID）："
        "\n{"
        "\n  \"origin\": {\"place_id\": \"…\", \"provider\": \"osm 或 amap 或 manual_verified\", \"kind\": \"city\", "
        "\"name\": \"…\", \"display_name\": \"…\", \"country_code\": \"两位国家码\", \"latitude\": 数值, \"longitude\": 数值, \"admin_path\": [\"…\"]},"
        "\n  \"destinations\": [同 origin 结构，一至五个，顺序即游览顺序],"
        "\n  \"start_date\": \"YYYY-MM-DD\", \"end_date\": \"YYYY-MM-DD\","
        "\n  \"party\": {\"adults\": 人数, \"children\": 人数, \"elderly_companions\": 布尔, \"accessibility_required\": 布尔},"
        "\n  \"style\": {\"primary\": \"简短风格短语\", \"secondary_interests\": [\"…\"], \"source\": \"current 或 suggested\"}"
        "\n}"
        "\n规则：地点 kind 必须原样使用英文枚举，不要翻译。出发地只允许 city、airport、train_station；"
        "目的地只允许 city、administrative_area、island、scenic_area。"
        "日期按参考日期解析相对表达；只有月份或季节等不确定表达时先问用户，不要擅自决定。"
        "独自旅行表示一位成人。单次旅行最多 14 天，目的地数量不能超过行程天数。"
        "end_date 减 start_date 加一为总天数。风格短语保持简短（如「经典均衡」「深度慢游」）。"
    )


def understanding_context_payload(state: Any) -> Dict[str, Any]:
    """首轮交给理解代理的用户上下文。"""

    payload: Dict[str, Any] = {
        "参考日期": state.current_time or "",
        "用户旅行想法": state.user_query,
        "长期偏好与记忆": format_constraint_pack_for_prompt(state.constraint_pack or {}),
        "其他背景": state.preset_context or "",
    }
    if state.current_requirements:
        payload["已有需求与最新补充"] = state.current_requirements
    if state.plan_gate_amendment is not None:
        payload["最新补充"] = state.plan_gate_amendment.content
    if state.pending_intent_amendments:
        payload["最新补充"] = [item.content for item in state.pending_intent_amendments]
    identity = getattr(state, "controlled_trip_identity", None)
    if identity:
        payload["已提供的表单基础信息"] = identity
    return payload


def initial_understanding_messages(state: Any) -> List[Dict[str, Any]]:
    return [
        {"role": "system", "content": understanding_system_prompt()},
        {
            "role": "user",
            "content": json.dumps(
                understanding_context_payload(state), ensure_ascii=False, default=str
            ),
        },
    ]
