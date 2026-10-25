"""Planning presentation."""

from __future__ import annotations

from typing import Dict
from typing import Final
import re


AGENT_DISPLAY_NAMES: Final[Dict[str, str]] = {
    "supervisor": "智能调度",
    "scope_clarifier": "需求确认",
    "request_contract_normalizer": "需求合同",
    "research_brief_builder": "调研简报",
    "minimum_delivery_draft_builder": "行程骨架",
    "intent_amendment_router": "要求更新",
    "trip_summary_card_brief": "旅行摘要",
    "destination_geo_resolver": "目的地定位",
    "weather_context_builder": "天气事实",
    "budget_estimate": "预算估算",
    "delivery_projector": "交付内容",
    "delivery_finalizer": "交付定稿",
    "planner": "任务规划",
    "plan_gate": "计划审批",
    "dispatcher": "任务分发",
    "candidate_gate": "候选校验",
    "artifact_gate": "产物校验",
    "intent_fidelity_gate": "意图校验",
    "delivery_quality_gate": "交付校验",
    "destination_researcher": "目的地调研",
    "transport_researcher": "交通查询",
    "accommodation_researcher": "住宿查询",
    "itinerary_planner": "行程规划",
    "fast_answer_agent": "旅行顾问",
}


STEP_DISPLAY_NAMES: Final[Dict[str, str]] = {
    "orchestrating": "编排调度",
    "planning": "制定计划",
    "researching": "调研分析",
    "synthesizing": "综合总结",
    "supervisor": "智能调度",
    "scope_clarifier": "需求确认",
    "request_contract_normalizer": "整理需求合同",
    "research_brief_builder": "生成调研简报",
    "minimum_delivery_draft_builder": "搭建行程骨架",
    "intent_amendment_router": "处理新增要求",
    "trip_summary_card_brief": "整理旅行摘要",
    "destination_geo_resolver": "确认目的地坐标",
    "weather_context_builder": "获取规划天气",
    "budget_estimate": "估算整趟预算",
    "delivery_projector": "生成交付内容",
    "delivery_finalizer": "封存交付结果",
    "planner": "任务规划",
    "plan_gate": "等待计划确认",
    "dispatcher": "任务分发",
    "candidate_gate": "校验候选质量",
    "artifact_gate": "校验调研产物",
    "intent_fidelity_gate": "校验意图覆盖",
    "delivery_quality_gate": "校验交付内容",
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
