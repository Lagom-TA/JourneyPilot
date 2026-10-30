"""会话收集契约。"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from travel_agent.planning.requirements.identity_contracts import (
    MAX_CONTROLLED_DESTINATIONS,
    ControlledTripIdentity,
    PlaceIdentity,
    TravelParty,
    TravelStyle,
)


class RouteName(str, Enum):
    TRIP_PLANNING = "trip_planning"
    DESTINATION_DISCOVERY = "destination_discovery"
    FAST_ANSWER = "fast_answer"
    TRIP_REFINEMENT = "trip_refinement"


class RouteAlternative(BaseModel):
    route: RouteName
    confidence: float = Field(ge=0, le=1)


class RouteDecision(BaseModel):
    route: RouteName
    confidence: float = Field(ge=0, le=1)
    alternatives: List[RouteAlternative] = Field(default_factory=list)
    signals: List[str] = Field(default_factory=list)
    requires_trip_draft: bool
    requires_confirmation: bool = False


class IntakeQuestionOption(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=120)


class IntakeQuestion(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=240)
    kind: Literal["single", "multiple"]
    options: List[IntakeQuestionOption] = Field(min_length=2, max_length=6)

    @model_validator(mode="after")
    def unique_options(self) -> "IntakeQuestion":
        if len({option.id for option in self.options}) != len(self.options):
            raise ValueError("问题选项不能重复")
        return self


class IntakeAnswer(BaseModel):
    question_id: str = Field(min_length=1, max_length=64)
    selected_option_ids: List[str] = Field(default_factory=list, max_length=6)
    supplement: str = Field(default="", max_length=500)


class IntakeAnswerRecord(BaseModel):
    question_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=240)
    answer: str = Field(min_length=1, max_length=1300)
    selected_option_ids: List[str] = Field(default_factory=list, max_length=6)
    selected_labels: List[str] = Field(default_factory=list, max_length=6)
    supplement: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_selected_options(self) -> "IntakeAnswerRecord":
        if len(self.selected_option_ids) != len(self.selected_labels):
            raise ValueError("归档选项与标签必须一一对应")
        if len(set(self.selected_option_ids)) != len(self.selected_option_ids):
            raise ValueError("归档选项不能重复")
        return self


class IntakeDestinationSuggestion(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=240)


class IntakeDraft(BaseModel):
    """模型识别的草稿，地点名称仍需从真实候选确认。"""

    origin_query: str = Field(default="", max_length=120)
    destination_queries: List[str] = Field(default_factory=list, max_length=MAX_CONTROLLED_DESTINATIONS)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    duration_days: Optional[int] = Field(default=None, ge=1, le=14)
    party: Optional[TravelParty] = None
    style: Optional[TravelStyle] = None
    budget_text: str = Field(default="", max_length=300)
    destination_decided: bool = False
    destination_suggestions: List[IntakeDestinationSuggestion] = Field(default_factory=list, max_length=3)
    confirmed_origin: Optional[PlaceIdentity] = None
    confirmed_destinations: List[PlaceIdentity] = Field(default_factory=list, max_length=MAX_CONTROLLED_DESTINATIONS)


MAX_INTAKE_QUESTIONS = 12
MAX_ARCHIVED_INTAKE_ANSWERS = 100
MAX_ARCHIVED_INTAKE_CHARS = 32000


class GuidedIntakeState(BaseModel):
    intake_id: Optional[str] = Field(default=None, pattern=r"^(?:it|legacy)_[0-9a-f]{32}$")
    intake_revision: int = Field(default=0, ge=0, strict=True)
    raw_input: str
    route_decision: RouteDecision
    controlled_identity: Optional[ControlledTripIdentity] = None
    seed_destinations: List[PlaceIdentity] = Field(default_factory=list, max_length=MAX_CONTROLLED_DESTINATIONS)
    draft: IntakeDraft = Field(default_factory=IntakeDraft)
    missing_fields: List[Literal["origin", "destinations", "dates", "party", "style", "place_confirmation"]] = Field(default_factory=list)
    ready_to_create: bool = False
    recognized_requirements: List[str] = Field(default_factory=list, max_length=12)
    questions: List[IntakeQuestion] = Field(default_factory=list, max_length=MAX_INTAKE_QUESTIONS)
    answers: List[IntakeAnswer] = Field(default_factory=list, max_length=MAX_INTAKE_QUESTIONS)
    archived_answers: List[IntakeAnswerRecord] = Field(default_factory=list, max_length=MAX_ARCHIVED_INTAKE_ANSWERS)
    additional_requirements: str = Field(default="", max_length=1000)
    understanding_status: Literal["ready", "unavailable"] = "ready"

    @model_validator(mode="after")
    def require_identity_before_creation(self) -> "GuidedIntakeState":
        question_ids = {question.id for question in self.questions}
        archived_ids = [item.question_id for item in self.archived_answers]
        if len(question_ids) != len(self.questions) or len(set(archived_ids)) != len(archived_ids):
            raise ValueError("问题标识不能重复")
        if question_ids & set(archived_ids):
            raise ValueError("当前问题不能重复已归档的问题标识")
        answers = {answer.question_id: answer for answer in self.answers}

        def complete(question: IntakeQuestion) -> bool:
            answer = answers.get(question.id)
            if answer is None:
                return False
            selected = answer.selected_option_ids
            return bool(selected or answer.supplement.strip()) and (
                len(selected) == len(set(selected))
                and set(selected) <= {option.id for option in question.options}
                and (question.kind != "single" or len(selected) <= 1)
            )

        questions_complete = (
            len(answers) == len(self.answers)
            and set(answers) <= {question.id for question in self.questions}
            and all(complete(question) for question in self.questions)
        )
        self.ready_to_create = (
            self.understanding_status == "ready"
            and self.controlled_identity is not None
            and not self.missing_fields
            and questions_complete
        )
        return self


def normalize_stored_intake(payload: dict, *, session_id: str, user_id: str) -> GuidedIntakeState:
    """给旧持久化草稿派生稳定 ID；只有客户端重新读取后才能提交。"""
    values = dict(payload)
    if not values.get("intake_id"):
        encoded = json.dumps(
            {"session_id": session_id, "user_id": user_id, "legacy_payload": payload},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        values["intake_id"] = "legacy_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]
    return GuidedIntakeState.model_validate(values)
