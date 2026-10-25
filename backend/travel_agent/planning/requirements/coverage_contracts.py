"""Planning requirements coverage contracts."""

from __future__ import annotations

from enum import Enum
from pydantic import Field
from pydantic import model_validator
from travel_agent.planning.requirements.intent_contracts import VerificationMode
from travel_agent.schema import StrictModel
from typing import List
from typing import Literal


INTENT_COVERAGE_VERSION = "journeypilot.intent_coverage.v1"


INTENT_FIDELITY_POLICY_VERSION = "intent_fidelity.v1"


class IntentCoverageStatus(str, Enum):
    SATISFIED = "satisfied"
    PARTIALLY_SATISFIED = "partially_satisfied"
    UNSATISFIED = "unsatisfied"
    UNVERIFIABLE = "unverifiable"
    UNSUPPORTED = "unsupported"
    CONFLICTED = "conflicted"


class CoverageEntityRef(StrictModel):
    entity_type: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)


class IntentDeviation(StrictModel):
    deviation_id: str = Field(min_length=1)
    intent_id: str = Field(min_length=1)
    status: Literal[
        "partially_satisfied",
        "unsatisfied",
        "unverifiable",
        "unsupported",
        "conflicted",
    ]
    reason_code: str = Field(min_length=1)
    public_explanation: str = Field(min_length=1, max_length=500)


class IntentCoverageItem(StrictModel):
    intent_id: str = Field(min_length=1)
    status: IntentCoverageStatus
    supporting_entity_refs: List[CoverageEntityRef] = Field(default_factory=list)
    supporting_candidate_ids: List[str] = Field(default_factory=list)
    supporting_fact_assertion_ids: List[str] = Field(default_factory=list)
    violated_entity_refs: List[CoverageEntityRef] = Field(default_factory=list)
    covered_days: List[int] = Field(default_factory=list)
    missing_days: List[int] = Field(default_factory=list)
    verification_mode: VerificationMode
    public_explanation: str = Field(min_length=1, max_length=500)
    blocking: bool


class IntentCoverageReport(StrictModel):
    schema_version: Literal[INTENT_COVERAGE_VERSION] = INTENT_COVERAGE_VERSION
    coverage_report_id: str = Field(min_length=1)
    generation_id: str = Field(min_length=1)
    intent_spec_revision: int = Field(ge=1)
    workspace_revision: int = Field(ge=0)
    items: List[IntentCoverageItem] = Field(default_factory=list)
    hard_satisfaction_rate: float = Field(ge=0.0, le=1.0)
    soft_coverage_rate: float = Field(ge=0.0, le=1.0)
    blocking_gap_ids: List[str] = Field(default_factory=list)
    deviations: List[IntentDeviation] = Field(default_factory=list)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_report(self) -> "IntentCoverageReport":
        intent_ids = [item.intent_id for item in self.items]
        if len(intent_ids) != len(set(intent_ids)):
            raise ValueError("intent coverage items must be unique")
        if not set(item.intent_id for item in self.deviations) <= set(intent_ids):
            raise ValueError("intent deviation references a missing coverage item")
        return self


class IntentFidelityGap(StrictModel):
    gap_id: str = Field(min_length=1)
    intent_id: str = Field(min_length=1)
    reason: Literal[
        "required_candidate_missing",
        "excluded_candidate_present",
        "quantity_rule_violated",
        "cadence_rule_missing",
        "time_window_violated",
        "sequence_rule_violated",
        "semantic_coverage_low",
        "output_requirement_missing",
        "intent_evidence_unavailable",
    ]
    blocking: bool
    retry_target: Literal[
        "candidate_gate",
        "candidate_selection",
        "itinerary_planner",
        "delivery_projection",
        "none",
    ]
    affected_entity_ids: List[str] = Field(default_factory=list)
    violated_rule_ids: List[str] = Field(default_factory=list)
    repair_context: dict = Field(default_factory=dict)
