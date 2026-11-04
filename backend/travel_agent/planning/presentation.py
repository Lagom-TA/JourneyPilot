"""规划阶段的展示名映射。"""

from __future__ import annotations

from typing import Dict
from typing import Final
import re


AGENT_DISPLAY_NAMES: Final[Dict[str, str]] = {
    "scope_clarifier": "需求确认",
    "understanding_agent": "理解旅行需求",
    "understanding_gate": "等待你的回答",
    "requirements_preparer": "整理需求",
    "research_plan_generator": "研究生成",
    "minimum_delivery_draft_builder": "行程框架",
    "intent_amendment_router": "要求更新",
    "trip_summary_card_brief": "旅行摘要",
    "destination_geo_resolver": "目的地定位",
    "weather_context_builder": "天气信息",
    "delivery_projector": "整理行程",
    "delivery_finalizer": "保存计划",
    "planner": "制定计划",
    "plan_gate": "确认方案",
    "dispatcher": "安排查询",
    "research_gate": "等待重试研究",
    "destination_researcher": "目的地调研",
    "transport_researcher": "交通查询",
    "accommodation_researcher": "住宿查询",
    "itinerary_planner": "行程规划",
    "fast_answer_agent": "旅行顾问",
}


STEP_DISPLAY_NAMES: Final[Dict[str, str]] = {
    "planning": "制定计划",
    "researching": "查询旅行资料",
    "synthesizing": "汇总旅行内容",
    "scope_clarifier": "确认旅行需求",
    "understanding_agent": "理解并核实旅行需求",
    "understanding_gate": "等待你的回答",
    "requirements_preparer": "整理旅行需求",
    "research_plan_generator": "生成研究计划",
    "minimum_delivery_draft_builder": "整理行程框架",
    "intent_amendment_router": "处理新增要求",
    "trip_summary_card_brief": "整理旅行摘要",
    "destination_geo_resolver": "确认目的地位置",
    "weather_context_builder": "查询旅行天气",
    "delivery_projector": "生成旅行内容",
    "delivery_finalizer": "保存完整计划",
    "planner": "制定规划安排",
    "plan_gate": "等待确认方案",
    "dispatcher": "安排旅行查询",
    "research_gate": "等待重试研究",
    "destination_researcher": "目的地调研",
    "transport_researcher": "交通方案查询",
    "accommodation_researcher": "住宿信息查询",
    "itinerary_planner": "行程规划",
    "fast_answer_agent": "智能解答",
}


_ROUND_SUFFIX_RE = re.compile(r"^(.+?)_r(\d+)$")


def get_agent_display_name(agent_name: str) -> str:
    """将 Agent 内部名转为中文显示名。

    查找策略：精确匹配 → 去 ``_rN`` 后缀匹配并格式化轮次 → 原样返回。
    """
    label = AGENT_DISPLAY_NAMES.get(agent_name)
    if label is not None:
        return label

    m = _ROUND_SUFFIX_RE.match(agent_name)
    if m:
        base_label = AGENT_DISPLAY_NAMES.get(m.group(1))
        if base_label is not None:
            return f"{base_label}（第{m.group(2)}轮补充）"

    return agent_name


def get_step_display_name(step_name: str) -> str:
    """将步骤/阶段内部名转为中文显示名，未匹配时原样返回。"""
    return STEP_DISPLAY_NAMES.get(step_name, step_name)
