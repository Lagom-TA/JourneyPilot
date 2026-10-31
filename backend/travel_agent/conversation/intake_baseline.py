"""条件表单入口的基线补充问题。

模型判断没有实质缺口时，条件表单用户仍看不到与这趟旅行有关的取舍。
这里提供一组只用已确认身份组织的固定问题，不替代模型评估：

- 只由 preparation 在「已确认身份 + 首次评估 + 模型没有出题」时追加；
- 每题都带统一的「按合理默认安排」出口，选择默认不产生正向研究要求；
- 问题与回答沿用现有 GuidedIntakeState / merge_intake_answers 链路。
"""

from __future__ import annotations

import re

from travel_agent.conversation.intake import (
    DEFAULT_ANSWER_LABEL,
    DEFAULT_ANSWER_OPTION_ID,
)
from travel_agent.conversation.intake_contracts import (
    GuidedIntakeState,
    IntakeQuestion,
    IntakeQuestionOption,
)
from travel_agent.planning.requirements.identity_contracts import (
    ControlledTripIdentity,
)
from travel_agent.planning.requirements.route_legs import required_route_names

BASELINE_PRIORITIES_QUESTION_ID = "baseline_priorities"
BASELINE_INTERCITY_QUESTION_ID = "baseline_intercity_transport"
BASELINE_LODGING_QUESTION_ID = "baseline_lodging"

_MAX_BASELINE_QUESTIONS = 3

_INTEREST_HINTS = re.compile(
    r"经典地标|地标|当地美食|美食|小吃|博物馆|人文|历史|自然风景|自然|风景"
)
_INTERCITY_HINTS = re.compile(r"高铁|动车|飞机|航班|自驾|大巴|火车")
_LODGING_HINTS = re.compile(r"住宿|酒店|民宿|客栈|住得|住在|安静")


def _default_option() -> IntakeQuestionOption:
    return IntakeQuestionOption(id=DEFAULT_ANSWER_OPTION_ID, label=DEFAULT_ANSWER_LABEL)


def _destination_names(identity: ControlledTripIdentity) -> list[str]:
    return [place.name for place in identity.destinations]


def _route_text(identity: ControlledTripIdentity) -> str:
    return " → ".join(required_route_names(identity.model_dump(mode="json")))


def _nights(identity: ControlledTripIdentity) -> int:
    return max(identity.duration_days - 1, 1)


def _material_text(intake: GuidedIntakeState) -> str:
    return "\n".join(
        part
        for part in (
            intake.raw_input.strip(),
            intake.additional_requirements.strip(),
            *[item.strip() for item in intake.recognized_requirements],
        )
        if part
    )


def _already_expressed(
    intake: GuidedIntakeState, pattern: re.Pattern[str]
) -> bool:
    return bool(pattern.search(_material_text(intake)))


def baseline_intake_questions(
    intake: GuidedIntakeState,
    identity: ControlledTripIdentity,
) -> list[IntakeQuestion]:
    """按本次受控身份生成最多三道可跳过的补充问题。

    已经明确提供的偏好不重复询问：风格里的明确兴趣不再问优先体验，
    原文/补充要求里写明城际方式或住宿取向时跳过对应问题。
    """

    destinations = _destination_names(identity)
    if not destinations:
        return []
    questions: list[IntakeQuestion] = []

    if not identity.style.secondary_interests and not _already_expressed(
        intake, _INTEREST_HINTS
    ):
        questions.append(
            IntakeQuestion(
                id=BASELINE_PRIORITIES_QUESTION_ID,
                question=f"这次去{'、'.join(destinations)}，最想优先安排什么？",
                kind="multiple",
                options=[
                    IntakeQuestionOption(id="landmarks", label="经典地标"),
                    IntakeQuestionOption(id="local_food", label="当地美食"),
                    IntakeQuestionOption(id="museums", label="博物馆/人文"),
                    IntakeQuestionOption(id="nature", label="自然风景"),
                    _default_option(),
                ],
            )
        )

    route = _route_text(identity)
    if route and not _already_expressed(intake, _INTERCITY_HINTS):
        questions.append(
            IntakeQuestion(
                id=BASELINE_INTERCITY_QUESTION_ID,
                question=f"{route}，城际交通更希望怎么安排？",
                kind="single",
                options=[
                    IntakeQuestionOption(id="rail_preferred", label="高铁/动车优先"),
                    IntakeQuestionOption(id="flight_preferred", label="飞机优先"),
                    IntakeQuestionOption(id="best_value", label="按时间与价格择优"),
                    _default_option(),
                ],
            )
        )

    if identity.duration_days > 1 and not _already_expressed(
        intake, _LODGING_HINTS
    ):
        questions.append(
            IntakeQuestion(
                id=BASELINE_LODGING_QUESTION_ID,
                question=(
                    f"{'、'.join(destinations)}住 {_nights(identity)} 晚，"
                    "住宿更看重什么？"
                ),
                kind="single",
                options=[
                    IntakeQuestionOption(id="near_transit", label="靠近地铁、减少换乘"),
                    IntakeQuestionOption(id="city_center", label="市中心步行方便"),
                    IntakeQuestionOption(id="quiet_rest", label="安静休息"),
                    IntakeQuestionOption(id="best_price", label="价格优先"),
                    _default_option(),
                ],
            )
        )

    return questions[:_MAX_BASELINE_QUESTIONS]


def intake_has_assessment_history(intake: GuidedIntakeState | None) -> bool:
    """Saved questions/answers mean this session is past its first assessment."""

    return intake is not None and bool(
        intake.questions or intake.answers or intake.archived_answers
    )


def append_baseline_intake_questions(
    intake: GuidedIntakeState,
    identity: ControlledTripIdentity,
    *,
    previous: GuidedIntakeState | None,
) -> GuidedIntakeState:
    """只在模型没有出题、且会话还没有任何问答历史时追加基线问题。"""

    if intake.questions or intake_has_assessment_history(previous):
        return intake
    questions = baseline_intake_questions(intake, identity)
    if not questions:
        return intake
    return intake.model_copy(update={"questions": questions})
