"""规划前的必要信息收集。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from openai import OpenAIError
from pydantic import ValidationError

from travel_agent.conversation.intake_contracts import GuidedIntakeState, IntakeDraft, RouteDecision
from travel_agent.llm.router import get_model_router
from travel_agent.llm.task_routing import TaskKind, llm_for_task
from travel_agent.utils.json_helpers import safe_parse_json

INTAKE_TIMEOUT_SECONDS = 45.0


class IntakeUnderstandingUnavailable(RuntimeError):
    """必要信息收集暂时不可用。"""


def _prompt(raw_input: str) -> list[dict[str, str]]:
    system = (
        "你是旅行规划的需求整理者。用户希望完成旅行规划，也可能还没有决定去哪。"
        "先识别原文明确的信息，不能把没有提及的事实当成用户确认。"
        "把明确出发地和目的地写成检索名称，不生成地点ID或坐标。"
        "只有明确选定城市或区域才把 destination_decided 设为 true；海边城市、适合独旅等是筛选条件，不是目的地。"
        "目的地未定且用户有偏好时，在 destination_suggestions 提供二至三个可比较城市及各自适配理由，不编造实时价格或保证。推荐不等于用户选定。"
        "用参考日期解析明确的相对日期；只有月份、近期、季节等不确定表达时日期保持 null。"
        "如果明确起始日和天数，可以计算结束日；不得擅自决定出发日期。"
        "独自旅行表示一位成人、零儿童；未提同行人时 party 为 null。"
        "style 为 null 表示没有明确风格，推荐风格只能标记 source=suggested。"
        "recognized_requirements 只复述用户明确表达的需求，包括预算、首次独旅、海边等，不能丢失。"
        "预算原文写入 budget_text。"
        "最多提出三道确实影响选择且无法从标准表单直接确定的问题。出发地、目的地、确切日期和人数由后续表单补齐，不要用泛化选项代替它们。"
        "用户预算覆盖范围不明时可以询问是否包含往返交通；用户未提预算、餐饮等可选偏好时不要为收集而追问。"
        "每题提供二至六个清晰选项，允许用户自由补充。已经回答的问题不得重复询问。"
        "只输出 JSON，必须包含 draft、recognized_requirements 和 questions；不输出行程，不声称信息已经足够。"
    )
    payload = {
        "reference_date": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
        "raw_input": raw_input,
        "output": {
            "draft": {
                "origin_query": "明确出发地，否则为空字符串",
                "destination_queries": ["明确选定的目的地检索名，否则空数组"],
                "destination_decided": False,
                "destination_suggestions": [{"name": "候选城市", "reason": "结合原文说明它适合什么、与其他候选有何取舍"}],
                "start_date": None, "end_date": None, "duration_days": None,
                "party": None, "style": None, "budget_text": "预算原文，否则空字符串",
            },
            "recognized_requirements": ["用户明确表达的需求"],
            "questions": [{"id": "简短英文标识", "question": "必要问题", "kind": "single 或 multiple", "options": [{"id": "简短英文标识", "label": "选项"}]}],
        },
    }
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def intake_missing_fields(draft: IntakeDraft, *, has_destinations: bool = False) -> list[str]:
    missing = []
    if not draft.origin_query:
        missing.append("origin")
    if not has_destinations and not (draft.destination_decided and draft.destination_queries):
        missing.append("destinations")
    if not draft.start_date or not draft.end_date or draft.end_date < draft.start_date:
        missing.append("dates")
    if draft.party is None:
        missing.append("party")
    missing.append("place_confirmation")
    return missing


def unavailable_intake(raw_input: str, route_decision: RouteDecision) -> GuidedIntakeState:
    return GuidedIntakeState(
        raw_input=raw_input, route_decision=route_decision,
        missing_fields=["origin", "destinations", "dates", "party", "place_confirmation"],
        understanding_status="unavailable",
    )


async def understand_trip_intake(raw_input: str, route_decision: RouteDecision, *, llm: Any = None) -> GuidedIntakeState:
    """识别已知信息，待补字段由业务规则计算，真实地点交由用户确认。"""
    try:
        model = llm or llm_for_task(get_model_router(), TaskKind.INTENT_NORMALIZE)
        response = await asyncio.wait_for(model.ainvoke(_prompt(raw_input), temperature=0), timeout=INTAKE_TIMEOUT_SECONDS)
        parsed = safe_parse_json(getattr(response, "content", response), strip_think_tags=True)
        if not isinstance(parsed, dict) or not {"draft", "recognized_requirements", "questions"} <= parsed.keys():
            raise ValueError("需求理解未返回完整结构")
        draft = IntakeDraft.model_validate(parsed["draft"])
        return GuidedIntakeState(
            raw_input=raw_input, route_decision=route_decision, draft=draft,
            recognized_requirements=parsed["recognized_requirements"], questions=parsed["questions"],
            missing_fields=intake_missing_fields(draft),
        )
    except (asyncio.TimeoutError, OpenAIError, TypeError, ValueError, RuntimeError, ValidationError, AttributeError) as exc:
        raise IntakeUnderstandingUnavailable("暂时无法整理旅行需求，请确认下方旅行信息后继续") from exc


def merge_intake_answers(intake: GuidedIntakeState) -> str:
    """原始输入保持不变，按当前回答重建一次需求文本。"""
    questions = {question.id: question for question in intake.questions}
    lines = [intake.raw_input.strip()]
    details = []
    for answer in intake.answers:
        question = questions.get(answer.question_id)
        if question is None:
            continue
        options = {option.id: option.label for option in question.options}
        selected = [options[option_id] for option_id in answer.selected_option_ids if option_id in options]
        parts = ["、".join(selected)] if selected else []
        if answer.supplement.strip():
            parts.append(answer.supplement.strip())
        if parts:
            details.append(f"{question.question}：{'；'.join(parts)}")
    if details:
        lines.extend(["", "用户补充确认：", *details])
    if intake.additional_requirements.strip():
        lines.append(f"其他补充：{intake.additional_requirements.strip()}")
    return "\n".join(lines).strip()


def validate_intake_answers(intake: GuidedIntakeState, *, require_complete: bool = True) -> None:
    """回答只能引用当前问题，完整提交不能遗漏必要问题。"""
    questions = {question.id: question for question in intake.questions}
    seen: set[str] = set()
    for answer in intake.answers:
        question = questions.get(answer.question_id)
        if question is None or answer.question_id in seen:
            raise ValueError("需求回答与当前问题不匹配")
        seen.add(answer.question_id)
        option_ids = {option.id for option in question.options}
        if len(set(answer.selected_option_ids)) != len(answer.selected_option_ids) or any(option_id not in option_ids for option_id in answer.selected_option_ids):
            raise ValueError("需求回答包含无效选项")
        if question.kind == "single" and len(answer.selected_option_ids) > 1:
            raise ValueError("单选题只能选择一个选项")
        if not answer.selected_option_ids and not answer.supplement.strip():
            raise ValueError("请回答当前问题")
    if require_complete and seen != set(questions):
        raise ValueError("请先补充尚未回答的旅行问题")


def apply_intake_answers(saved: GuidedIntakeState, submitted: GuidedIntakeState) -> GuidedIntakeState:
    """问题和原文来自服务端，客户端仅更新本轮回答与未确认草稿。"""
    updated = saved.model_copy(update={"answers": [answer for answer in submitted.answers if answer.selected_option_ids or answer.supplement.strip()], "additional_requirements": submitted.additional_requirements, "draft": submitted.draft})
    validate_intake_answers(updated, require_complete=False)
    from travel_agent.planning.requirements.identity_contracts import ORIGIN_PLACE_KINDS, DESTINATION_PLACE_KINDS
    draft = updated.draft
    if draft.confirmed_origin and draft.confirmed_origin.kind not in ORIGIN_PLACE_KINDS:
        raise ValueError("出发地请选择城市、机场或火车站")
    if any(place.kind not in DESTINATION_PLACE_KINDS for place in draft.confirmed_destinations):
        raise ValueError("目的地请选择城市或区域")
    missing = []
    if draft.confirmed_origin is None:
        missing.append("origin")
    if not draft.confirmed_destinations:
        missing.append("destinations")
    if not draft.start_date or not draft.end_date or draft.end_date < draft.start_date:
        missing.append("dates")
    if draft.party is None:
        missing.append("party")
    return updated.model_copy(update={"missing_fields": missing, "ready_to_create": False})
