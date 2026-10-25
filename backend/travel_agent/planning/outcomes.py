from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional

from pydantic import Field, model_validator

from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.schema import StrictModel


class GateClass(str, Enum):
    COMPOSITION = "composition"


class CandidateResearchGap(StrictModel):
    gap_id: str = Field(min_length=1)
    worker_kind: Literal[
        "destination_researcher", "accommodation_researcher", "transport_researcher"
    ]
    reason: Literal[
        "missing_candidate",
        "missing_comparison_fact",
        "missing_intent_candidate",
        "insufficient_intent_evidence",
        "selection_coverage_gap",
    ]
    generation_id: str = Field(min_length=1)
    intent_id: Optional[str] = None
    query_id: Optional[str] = None
    desired_candidate_count: Optional[int] = Field(default=None, ge=1)
    candidate_id: Optional[str] = None
    selection_slot_id: Optional[str] = None
    field_path: Optional[str] = None
    destination_id: Optional[str] = None
    provider_evidence_scope_id: Optional[str] = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    gate_class: GateClass = GateClass.COMPOSITION
    research_domain: Optional[ResearchDomain] = None
    status: Literal[
        "open",
        "researching",
        "resolved",
        "exhausted",
    ] = "open"
    attempted_signatures: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scope(self) -> "CandidateResearchGap":
        intent_reasons = {
            "missing_intent_candidate",
            "insufficient_intent_evidence",
            "selection_coverage_gap",
        }
        if self.reason in intent_reasons and self.intent_id is None:
            raise ValueError("intent-scoped gap requires intent id")
        if (
            self.reason not in {"missing_candidate", *intent_reasons}
            and self.candidate_id is None
        ):
            raise ValueError("candidate-scoped gap requires candidate id")
        if self.reason == "missing_comparison_fact" and self.field_path is None:
            raise ValueError("field-scoped candidate gap requires field path")
        is_long_distance = self.field_path == "transport_class.long_distance"
        if is_long_distance and self.provider_evidence_scope_id is None:
            raise ValueError(
                "long-distance candidate gap requires exact Provider evidence scope"
            )
        if not is_long_distance and self.provider_evidence_scope_id is not None:
            raise ValueError(
                "only long-distance candidate gaps may bind Provider evidence scope"
            )
        return self


class InternalFailureClass(str, Enum):
    TRANSIENT_DEPENDENCY = "transient_dependency"
    RESEARCH_GAP = "research_gap"
    CONTRACT_VIOLATION = "contract_violation"
    PROJECTION_FAILURE = "projection_failure"
    PERSISTENCE_FAILURE = "persistence_failure"
    SAFETY_BLOCK = "safety_block"
    USER_DECISION_REQUIRED = "user_decision_required"


class DeliveryFailureRecord(StrictModel):
    failure_class: InternalFailureClass
    operation: str = Field(min_length=1)
    attempts: int = Field(ge=1)
    retry_exhausted: bool
    public_message: str = Field(min_length=1)
