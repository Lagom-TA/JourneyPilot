"""会话收集契约。"""

from __future__ import annotations

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


class GuidedIntakeState(BaseModel):
    raw_input: str
    route_decision: RouteDecision
    controlled_identity: Optional[ControlledTripIdentity] = None
    seed_destinations: List[PlaceIdentity] = Field(default_factory=list, max_length=MAX_CONTROLLED_DESTINATIONS)
    draft: IntakeDraft = Field(default_factory=IntakeDraft)
    missing_fields: List[Literal["origin", "destinations", "dates", "party", "style", "place_confirmation"]] = Field(default_factory=list)
    ready_to_create: bool = False
    recognized_requirements: List[str] = Field(default_factory=list, max_length=12)
    questions: List[IntakeQuestion] = Field(default_factory=list, max_length=4)
    answers: List[IntakeAnswer] = Field(default_factory=list, max_length=4)
    additional_requirements: str = Field(default="", max_length=1000)
    understanding_status: Literal["ready", "unavailable"] = "ready"

    @model_validator(mode="after")
    def require_identity_before_creation(self) -> "GuidedIntakeState":
        if len({question.id for question in self.questions}) != len(self.questions):
            raise ValueError("问题标识不能重复")
        answered = {answer.question_id for answer in self.answers}
        questions_complete = all(
            question.id in answered for question in self.questions
        )
        self.ready_to_create = (
            self.controlled_identity is not None
            and not self.missing_fields
            and questions_complete
        )
        return self
