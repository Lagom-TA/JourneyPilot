"""规划前的必要信息收集。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from datetime import datetime
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from openai import OpenAIError
from pydantic import ValidationError

from travel_agent.conversation.intake_contracts import (
    GuidedIntakeState,
    IntakeAnswer,
    IntakeAnswerRecord,
    IntakeDraft,
    IntakeQuestion,
    IntakeQuestionOption,
    MAX_ARCHIVED_INTAKE_ANSWERS,
    MAX_ARCHIVED_INTAKE_CHARS,
    MAX_INTAKE_QUESTIONS,
    RouteDecision,
)
from travel_agent.llm.router import get_model_router
from travel_agent.llm.task_routing import TaskKind, llm_for_task
from travel_agent.llm.token_counting import estimate_request_tokens
from travel_agent.planning.requirements.identity_contracts import ControlledTripIdentity
from travel_agent.utils.json_helpers import safe_parse_json

INTAKE_TIMEOUT_SECONDS = 45.0
INTAKE_PROMPT_MAX_ESTIMATED_TOKENS = 12000

# 服务端统一的“不继续补充”出口。它只是一项普通问题选项，不新增持久化字段；
# 用户选择后会和其它回答一起进入同一份需求文本，避免把显式默认误读成“未知”。
DEFAULT_ANSWER_OPTION_ID = "sensible_default"
DEFAULT_ANSWER_LABEL = "按合理默认安排，不再补充"

_IDENTITY_QUESTION_IDS = {
    "origin",
    "destination",
    "destinations",
    "trip_dates",
    "date",
    "dates",
    "date_range",
    "party",
    "travelers",
    "travel_party",
}
# 只有“真的在问身份字段”的句子才视为重复身份问题。仅出现“出发地”“目的地”
# 等词不代表身份未知，例如“总预算是否包含出发地至目的地的往返交通？”仍是
# 需要保留的预算覆盖范围缺口。
_IDENTITY_QUESTION_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"^\s*(?:请问)?(?:你|你们)?(?:打算|计划|准备)?(?:从|由)?(?:哪里|哪儿|哪座城市|哪个城市)[^？?。]{0,8}(?:出发|启程)",
        r"^\s*(?:请问)?(?:你|你们)?(?:的)?出发地[^？?。]{0,10}(?:是|为|在)[^？?。]{0,6}(?:哪|什么|何处)",
        r"^\s*(?:请问)?(?:你|你们)?(?:的)?目的地[^？?。]{0,10}(?:是|为|在)[^？?。]{0,6}(?:哪|什么|何处)",
        r"^\s*(?:请问)?(?:你|你们)?(?:打算|计划|准备|想)?去(?:哪些|哪几个|哪个|哪座)[^？?。]{0,8}(?:城市|地方)",
        r"^\s*(?:请问)?(?:你|你们)?(?:计划|打算|准备)?(?:什么时候|哪天|哪几天|几号|几月几号|何时)[^？?。]{0,10}(?:出发|启程|去|开始|旅行)",
        r"^\s*(?:请问)?(?:你|你们)?(?:的)?(?:出发|返程|行程|旅行)日期[^？?。]{0,10}(?:是|为|在)[^？?。]{0,6}(?:哪|什么|几)",
        r"^\s*(?:请问)?(?:你|你们)?(?:几个人|几人|几位|多少人|和谁)[^？?。]{0,10}(?:去|一起|同行|旅行|出发)?\s*[？?]?\s*$",
    )
)


class IntakeUnderstandingUnavailable(RuntimeError):
    """必要信息收集暂时不可用。"""


class IntakeRevisionStale(ValueError):
    """The client edited an older server-saved intake."""

    def __init__(self, current_revision: int) -> None:
        self.current_revision = current_revision
        super().__init__("旅行需求已更新，请刷新后重新核对。")


def advance_intake_revision(
    previous: GuidedIntakeState | None, updated: GuidedIntakeState
) -> GuidedIntakeState:
    payload = updated.model_dump(mode="json")
    payload["intake_id"] = previous.intake_id if previous else "it_" + uuid.uuid4().hex
    if not payload["intake_id"]:
        raise IntakeRevisionStale(previous.intake_revision if previous else 0)
    payload["intake_revision"] = (previous.intake_revision if previous else 0) + 1
    return GuidedIntakeState.model_validate(payload)


def intake_edit_effects_equal(left: GuidedIntakeState, right: GuidedIntakeState) -> bool:
    def answers(state: GuidedIntakeState) -> dict[str, object]:
        return {item.question_id: item.model_dump(mode="json") for item in state.answers}

    return (
        answers(left) == answers(right)
        and left.draft == right.draft
        and left.additional_requirements == right.additional_requirements
    )


def controlled_identity_summary(identity: ControlledTripIdentity) -> str:
    """把已确认身份压成一段可供评估、需求文本和计划展示复用的公开摘要。"""
    destinations = " → ".join(place.name for place in identity.destinations)
    party = f"{identity.party.adults}位成人"
    if identity.party.children:
        party += f"、{identity.party.children}位儿童"
    if identity.party.elderly_companions:
        party += "、长辈同行"
    if identity.party.accessibility_required:
        party += "、需要无障碍安排"
    style = identity.style.primary
    if identity.style.secondary_interests:
        style += f"（{'、'.join(identity.style.secondary_interests)}）"
    return (
        f"从{identity.origin.name}出发，按{destinations}的顺序，"
        f"{identity.start_date.isoformat()} 至 {identity.end_date.isoformat()}"
        f"（共{identity.duration_days}天），{party}，旅行风格：{style}。"
    )


def _current_answered_material(previous: GuidedIntakeState | None) -> list[dict[str, str]]:
    if previous is None:
        return []
    questions = {question.id: question for question in previous.questions}
    rows: list[dict[str, str]] = []
    for answer in previous.answers:
        question = questions.get(answer.question_id)
        if question is None:
            continue
        options = {option.id: option.label for option in question.options}
        selected = [
            options[option_id]
            for option_id in answer.selected_option_ids
            if option_id in options
        ]
        text = "；".join([*selected, answer.supplement.strip()]).strip("；")
        if text:
            rows.append({"question_id": question.id, "question": question.question, "answer": text})
    return rows


def _answered_material(previous: GuidedIntakeState | None) -> list[dict[str, str]]:
    if previous is None:
        return []
    archived = [{"question": item.question, "answer": item.answer} for item in previous.archived_answers]
    current = [{"question": item["question"], "answer": item["answer"]} for item in _current_answered_material(previous)]
    return [*archived, *current]


def _prompt(
    raw_input: str,
    *,
    controlled_identity: ControlledTripIdentity | None = None,
    previous: GuidedIntakeState | None = None,
) -> list[dict[str, str]]:
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
        "如果 confirmed_trip_identity 已给出，出发地、目的地及顺序、日期、同行和风格都已确认，不得再问这些字段，也不得要求用户重复确认；"
        "但预算覆盖范围、必去/排除项、节奏取舍等仍可能实质改变研究范围的信息可以问。"
        "additional_requirements 是用户在确认前补充的实质要求，必须和原文、已答内容一起评估，不能遗漏或重复询问其中已明确的信息。"
        "如果综合已确认身份、原文、补充要求和已答内容后没有会改变研究范围或可执行方案的实质缺口，questions 返回空数组；不要为了提问而提问。"
        "不要断言“信息已经足够”，也不要在信息不足时伪造完成判断。"
        "只输出 JSON，必须包含 draft、recognized_requirements 和 questions；不输出行程。"
    )
    payload = {
        "reference_date": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
        "raw_input": raw_input,
        "confirmed_trip_identity": (
            controlled_identity.model_dump(mode="json")
            if controlled_identity is not None
            else None
        ),
        "already_answered": _answered_material(previous),
        "additional_requirements": (
            previous.additional_requirements if previous is not None else ""
        ),
        "output": {
            "draft": {
                "origin_query": "明确出发地，否则为空字符串",
                "destination_queries": ["明确选定的目的地检索名，否则空数组"],
                "destination_decided": False,
                "destination_suggestions": [
                    {
                        "name": "候选城市",
                        "reason": "结合原文说明它适合什么、与其他候选有何取舍",
                    }
                ],
                "start_date": None,
                "end_date": None,
                "duration_days": None,
                "party": None,
                "style": None,
                "budget_text": "预算原文，否则空字符串",
            },
            "recognized_requirements": ["用户明确表达的需求"],
            "questions": [
                {
                    "id": "简短英文标识",
                    "question": "必要问题",
                    "kind": "single 或 multiple",
                    "options": [
                        {"id": "简短英文标识", "label": "选项"}
                    ],
                }
            ],
        },
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def intake_missing_fields(
    draft: IntakeDraft, *, has_destinations: bool = False
) -> list[str]:
    missing = []
    if not draft.origin_query:
        missing.append("origin")
    if not has_destinations and not (
        draft.destination_decided and draft.destination_queries
    ):
        missing.append("destinations")
    if not draft.start_date or not draft.end_date or draft.end_date < draft.start_date:
        missing.append("dates")
    if draft.party is None:
        missing.append("party")
    missing.append("place_confirmation")
    return missing


def unavailable_intake(
    raw_input: str, route_decision: RouteDecision
) -> GuidedIntakeState:
    return GuidedIntakeState(
        raw_input=raw_input,
        route_decision=route_decision,
        missing_fields=[
            "origin",
            "destinations",
            "dates",
            "party",
            "place_confirmation",
        ],
        understanding_status="unavailable",
    )


def _with_default_option(
    question: IntakeQuestion, *, trim_to_make_room: bool = False
) -> IntakeQuestion:
    if any(option.id == DEFAULT_ANSWER_OPTION_ID for option in question.options):
        return question
    options = list(question.options)
    # 已保存问题里的选项可能正被历史回答引用，不能为了追加默认出口丢弃它。
    if len(options) >= 6:
        if not trim_to_make_room:
            return question
        options = options[:5]
    options.append(
        IntakeQuestionOption(id=DEFAULT_ANSWER_OPTION_ID, label=DEFAULT_ANSWER_LABEL)
    )
    return question.model_copy(update={"options": options})


def _is_identity_question(question: IntakeQuestion) -> bool:
    if question.id.strip().lower() in _IDENTITY_QUESTION_IDS:
        return True
    text = question.question.strip()
    return any(pattern.search(text) for pattern in _IDENTITY_QUESTION_PATTERNS)


def _question_text_key(question: IntakeQuestion) -> str:
    return " ".join(question.question.split()).casefold()


def _prepare_questions(
    raw_questions: Sequence[Any],
    *,
    previous: GuidedIntakeState | None,
    controlled_identity: ControlledTripIdentity | None,
    max_new: int,
) -> tuple[list[IntakeQuestion], list[IntakeAnswer]]:
    answered = {answer.question_id for answer in (previous.answers if previous else [])}
    answered_texts = {
        _question_text_key(question)
        for question in (previous.questions if previous else [])
        if question.id in answered
    }
    history = [
        _with_default_option(question)
        for question in (previous.questions if previous else [])
        if question.id in answered
    ]
    questions: list[IntakeQuestion] = []
    if max_new <= 0:
        return history, list(previous.answers if previous else [])
    seen_ids = {question.id for question in history} | {
        item.question_id for item in (previous.archived_answers if previous else [])
    }
    seen_texts = {
        *answered_texts,
        *(" ".join(item.question.split()).casefold() for item in (previous.archived_answers if previous else [])),
    }
    for raw in raw_questions:
        question = IntakeQuestion.model_validate(raw)
        if controlled_identity is not None and _is_identity_question(question):
            continue
        text_key = _question_text_key(question)
        if text_key in seen_texts:
            continue
        if question.id in seen_ids:
            # Models can reuse an identifier for a genuinely different follow-up.
            # Keep the new question with a server-generated, stable identifier.
            digest = hashlib.sha256(text_key.encode("utf-8")).hexdigest()[:12]
            question = question.model_copy(update={"id": f"{question.id[:51]}_{digest}"})
            if question.id in seen_ids:
                raise ValueError("需求问题标识冲突")
        seen_ids.add(question.id)
        seen_texts.add(text_key)
        questions.append(_with_default_option(question, trim_to_make_room=True))
        if len(questions) >= max_new:
            break
    return [*history, *questions], list(previous.answers if previous else [])


def _draft_for_identity(
    parsed_draft: Mapping[str, Any], identity: ControlledTripIdentity
) -> IntakeDraft:
    draft = dict(parsed_draft)
    draft.update(
        {
            "origin_query": identity.origin.name,
            "destination_queries": [
                place.name for place in identity.destinations
            ],
            "destination_decided": True,
            "destination_suggestions": [],
            "start_date": identity.start_date,
            "end_date": identity.end_date,
            "duration_days": identity.duration_days,
            "party": identity.party.model_dump(mode="json"),
            "style": identity.style.model_dump(mode="json"),
            "confirmed_origin": identity.origin.model_dump(mode="json"),
            "confirmed_destinations": [
                place.model_dump(mode="json") for place in identity.destinations
            ],
        }
    )
    return IntakeDraft.model_validate(draft)


def _coerce_identity(
    value: ControlledTripIdentity | Mapping[str, Any] | None,
) -> ControlledTripIdentity | None:
    if value is None or isinstance(value, ControlledTripIdentity):
        return value
    return ControlledTripIdentity.model_validate(value)


async def understand_trip_intake(
    raw_input: str,
    route_decision: RouteDecision,
    *,
    llm: Any = None,
    controlled_identity: ControlledTripIdentity | Mapping[str, Any] | None = None,
    previous: GuidedIntakeState | None = None,
) -> GuidedIntakeState:
    """服务端唯一的实质缺口评估入口。

    条件表单与自然语言入口都从这里得到问题和识别结果。已确认身份只作为
    输入，不替代评估；已答过的问题不重复出现，问题里固定提供“按合理默认”
    的普通选项。
    """
    identity = _coerce_identity(controlled_identity)
    try:
        messages = _prompt(raw_input, controlled_identity=identity, previous=previous)
        estimated_tokens, _ = estimate_request_tokens({"messages": messages})
        if estimated_tokens > INTAKE_PROMPT_MAX_ESTIMATED_TOKENS:
            raise IntakeUnderstandingUnavailable(
                "已保存的要求过长，请复制保留的信息并开始新旅行；尚未创建调研任务。"
            )
        model = llm or llm_for_task(get_model_router(), TaskKind.INTENT_NORMALIZE)
        response = await asyncio.wait_for(
            model.ainvoke(
                messages,
                temperature=0,
            ),
            timeout=INTAKE_TIMEOUT_SECONDS,
        )
        parsed = safe_parse_json(
            getattr(response, "content", response), strip_think_tags=True
        )
        if not isinstance(parsed, dict) or not {
            "draft",
            "recognized_requirements",
            "questions",
        } <= parsed.keys():
            raise ValueError("需求理解未返回完整结构")
        if not isinstance(parsed["questions"], list):
            raise ValueError("需求问题必须是数组")
        questions, answers = _prepare_questions(
            parsed["questions"],
            previous=previous,
            controlled_identity=identity,
            # Detect overflow rather than silently treating unanswered questions
            # as completed when the saved conversation reaches its bound.
            max_new=MAX_INTAKE_QUESTIONS + 1,
        )
        if len(questions) > MAX_INTAKE_QUESTIONS and previous is not None:
            previous = compact_answer_history(previous)
            questions, answers = _prepare_questions(
                parsed["questions"], previous=previous, controlled_identity=identity,
                max_new=MAX_INTAKE_QUESTIONS + 1,
            )
        if len(questions) > MAX_INTAKE_QUESTIONS:
            raise IntakeUnderstandingUnavailable(
                "本轮待确认的问题过多，请精简要求后重试；尚未创建调研任务。"
            )
        draft = (
            _draft_for_identity(parsed["draft"], identity)
            if identity is not None
            else IntakeDraft.model_validate(parsed["draft"])
        )
        return GuidedIntakeState(
            intake_id=previous.intake_id if previous else None,
            intake_revision=previous.intake_revision if previous else 0,
            raw_input=raw_input,
            route_decision=route_decision,
            controlled_identity=identity,
            draft=draft,
            recognized_requirements=parsed["recognized_requirements"],
            questions=questions,
            answers=answers,
            archived_answers=previous.archived_answers if previous else [],
            additional_requirements=(
                previous.additional_requirements if previous else ""
            ),
            missing_fields=(
                [] if identity is not None else intake_missing_fields(draft)
            ),
        )
    except IntakeUnderstandingUnavailable:
        raise
    except (
        asyncio.TimeoutError,
        OpenAIError,
        TypeError,
        ValueError,
        RuntimeError,
        ValidationError,
        AttributeError,
    ) as exc:
        raise IntakeUnderstandingUnavailable(
            "暂时无法整理旅行需求，请确认下方旅行信息后继续"
        ) from exc


def merge_intake_answers(intake: GuidedIntakeState) -> str:
    """原始输入保持不变，按当前回答重建一次需求文本。"""
    questions = {question.id: question for question in intake.questions}
    lines = [intake.raw_input.strip()]
    details = [f"{item.question}：{item.answer}" for item in intake.archived_answers]
    for answer in intake.answers:
        question = questions.get(answer.question_id)
        if question is None:
            continue
        options = {option.id: option.label for option in question.options}
        selected = [
            options[option_id]
            for option_id in answer.selected_option_ids
            if option_id in options
        ]
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


def compact_answer_history(intake: GuidedIntakeState) -> GuidedIntakeState:
    """归档已回答问题，保留原文与完整答案以便安全继续。"""
    validate_intake_answers(intake)
    answered = {answer.question_id for answer in intake.answers}
    questions = {question.id: question for question in intake.questions}
    answers = {answer.question_id: answer for answer in intake.answers}
    archive = []
    for item in _current_answered_material(intake):
        question = questions[item["question_id"]]
        answer = answers[question.id]
        options = {option.id: option.label for option in question.options}
        archive.append(IntakeAnswerRecord.model_validate({
            **item,
            "selected_option_ids": answer.selected_option_ids,
            "selected_labels": [options[option_id] for option_id in answer.selected_option_ids],
            "supplement": answer.supplement,
        }))
    retained = [question for question in intake.questions if question.id not in answered]
    all_archived = [*intake.archived_answers, *archive]
    if (
        len(all_archived) > MAX_ARCHIVED_INTAKE_ANSWERS
        or sum(len(item.question) + len(item.answer) for item in all_archived) > MAX_ARCHIVED_INTAKE_CHARS
    ):
        raise IntakeUnderstandingUnavailable(
            "已回答的问题过多，请复制保留的要求后开始新旅行；尚未创建调研任务。"
        )
    return intake.model_copy(update={
        "archived_answers": all_archived,
        "questions": retained,
        "answers": [],
        "ready_to_create": False,
    })


def validate_intake_answers(
    intake: GuidedIntakeState, *, require_complete: bool = True
) -> None:
    """回答只能引用当前问题，完整提交不能遗漏必要问题。"""
    questions = {question.id: question for question in intake.questions}
    seen: set[str] = set()
    for answer in intake.answers:
        question = questions.get(answer.question_id)
        if question is None or answer.question_id in seen:
            raise ValueError("需求回答与当前问题不匹配")
        seen.add(answer.question_id)
        option_ids = {option.id for option in question.options}
        if len(set(answer.selected_option_ids)) != len(
            answer.selected_option_ids
        ) or any(
            option_id not in option_ids
            for option_id in answer.selected_option_ids
        ):
            raise ValueError("需求回答包含无效选项")
        if question.kind == "single" and len(answer.selected_option_ids) > 1:
            raise ValueError("单选题只能选择一个选项")
        if not answer.selected_option_ids and not answer.supplement.strip():
            raise ValueError("请回答当前问题")
    if require_complete and seen != set(questions):
        raise ValueError("请先补充尚未回答的旅行问题")


def intake_answers_complete(intake: GuidedIntakeState) -> bool:
    try:
        validate_intake_answers(intake, require_complete=True)
    except ValueError:
        return False
    return True


def apply_intake_answers(
    saved: GuidedIntakeState, submitted: GuidedIntakeState
) -> GuidedIntakeState:
    """问题和原文来自服务端，客户端仅更新本轮回答与未确认草稿。"""
    if (
        not {"intake_id", "intake_revision"} <= submitted.model_fields_set
        or not submitted.intake_id
        or submitted.intake_id != saved.intake_id
    ):
        raise IntakeRevisionStale(saved.intake_revision)
    submitted_answers = [
        answer
        for answer in submitted.answers
        if answer.selected_option_ids or answer.supplement.strip()
    ]
    submitted_ids = {answer.question_id for answer in submitted_answers}
    # 客户端可能只回传本轮新问题的回答；服务端已保存的回答不能因此丢失。
    answers = [
        *[
            answer
            for answer in saved.answers
            if answer.question_id not in submitted_ids
        ],
        *submitted_answers,
    ]
    updated = saved.model_copy(
        update={
            "answers": answers,
            "additional_requirements": submitted.additional_requirements,
            "draft": submitted.draft,
        }
    )
    validate_intake_answers(updated, require_complete=False)
    from travel_agent.planning.requirements.identity_contracts import (
        DESTINATION_PLACE_KINDS,
        ORIGIN_PLACE_KINDS,
    )

    draft = updated.draft
    if (
        draft.confirmed_origin
        and draft.confirmed_origin.kind not in ORIGIN_PLACE_KINDS
    ):
        raise ValueError("出发地请选择城市、机场或火车站")
    if any(
        place.kind not in DESTINATION_PLACE_KINDS
        for place in draft.confirmed_destinations
    ):
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
    updated = updated.model_copy(update={"missing_fields": missing, "ready_to_create": False})
    if submitted.intake_revision != saved.intake_revision:
        if intake_edit_effects_equal(saved, updated):
            return saved
        raise IntakeRevisionStale(saved.intake_revision)
    return updated
