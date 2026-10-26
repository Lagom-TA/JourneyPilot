"""需求归一化契约。"""

from __future__ import annotations

from dataclasses import dataclass
from pydantic import Field
from pydantic import model_validator
from travel_agent.planning.requirements.intent_contracts import IntentImpactStage
from travel_agent.planning.requirements.intent_contracts import IntentKind
from travel_agent.planning.requirements.intent_contracts import IntentStrength
from travel_agent.planning.requirements.intent_contracts import IntentTarget
from travel_agent.planning.requirements.intent_contracts import IntentValue
from travel_agent.planning.requirements.intent_contracts import VerificationMode
from travel_agent.planning.requirements.request_contracts import ClauseDisposition
from travel_agent.schema import StrictModel
from typing import Dict
from typing import List
from typing import Literal
from typing import Optional


class ConstraintParamsDraft(StrictModel):
    amount: Optional[float] = None
    currency: Optional[str] = None
    per: Optional[Literal["night", "day", "total"]] = None
    allergens: List[str] = Field(default_factory=list)
    avoid_overnight: Optional[bool] = None
    earliest_departure_local: Optional[str] = None
    latest_arrival_local: Optional[str] = None
    preferred_local_modes: List[str] = Field(default_factory=list)
    excluded_local_modes: List[str] = Field(default_factory=list)
    locked_local_mode: Optional[str] = None
    required_facilities: List[str] = Field(default_factory=list)
    max_continuous_walk_minutes: Optional[int] = Field(default=None, ge=1)
    avoid_long_stairs: Optional[bool] = None
    prefer: List[str] = Field(default_factory=list)
    unknown_facility_policy: Optional[Literal["needs_confirmation"]] = None

    def compact(self) -> Dict[str, object]:
        return self.model_dump(exclude_none=True, exclude_defaults=True)


class NormalizedConstraintDraft(StrictModel):
    category: Literal[
        "food_allergy",
        "budget_cap",
        "elderly_mobility",
        "child_friendly",
        "transport_constraint",
        "accommodation_preference",
        "pace_preference",
        "destination_preference",
        "dietary_restriction",
        "health_condition",
        "other",
    ]
    value: str = Field(min_length=1, max_length=300)
    params: ConstraintParamsDraft = Field(default_factory=ConstraintParamsDraft)


class IntentDraft(StrictModel):
    kind: IntentKind
    target: IntentTarget
    strength: IntentStrength
    priority: int = Field(ge=0, le=100)
    value: IntentValue
    verification_mode: VerificationMode
    impact_stages: List[IntentImpactStage] = Field(min_length=1)
    public_summary: str = Field(min_length=1, max_length=300)


class NormalizedClauseDraft(StrictModel):
    clause_id: str = Field(min_length=1)
    disposition: ClauseDisposition
    reason_code: Optional[str] = None
    intents: List[IntentDraft] = Field(default_factory=list)
    constraints: List[NormalizedConstraintDraft] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_mapping(self) -> "NormalizedClauseDraft":
        if self.disposition is ClauseDisposition.MAPPED_TO_INTENT and not self.intents:
            raise ValueError("mapped clause requires an intent draft")
        if (
            self.disposition is ClauseDisposition.MAPPED_TO_CONSTRAINT
            and not self.constraints
        ):
            raise ValueError("constraint-mapped clause requires a constraint draft")
        if self.disposition is not ClauseDisposition.MAPPED_TO_INTENT and self.intents:
            raise ValueError("only mapped clauses may contain intent drafts")
        if (
            self.disposition
            in {
                ClauseDisposition.UNSUPPORTED,
                ClauseDisposition.UNRESOLVED,
            }
            and not self.reason_code
        ):
            raise ValueError("unsupported or unresolved clause requires a reason code")
        return self


class RequestContractNormalizationResult(StrictModel):
    clauses: List[NormalizedClauseDraft] = Field(min_length=1)


@dataclass(frozen=True)
class SourceClause:
    clause_id: str
    source_ref_id: str
    source_kind: str
    source_text: str
    span_start: int
    span_end: int
