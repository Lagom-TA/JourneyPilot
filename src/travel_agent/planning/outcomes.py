from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import Field, model_validator

from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.schema import StrictModel


class GateClass(str, Enum):
    COMPOSITION = "composition"


class GateDisposition(str, Enum):
    TARGETED_RESEARCH = "targeted_research"
    COMPOSITION_REPAIR = "composition_repair"

    RESEARCH_EXHAUSTED = "research_exhausted"


class DeliveryContractViolation(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        reason_code: str,
        gate_class: GateClass,
    ) -> None:
        self.reason_code = reason_code
        self.gate_class = gate_class
        super().__init__(message)


class GateFailureAttribution(StrictModel):
    attribution_id: str = Field(min_length=1)

    draft_id: Optional[str] = Field(default=None, min_length=1)
    gate_class: GateClass
    disposition: GateDisposition
    reason_code: str = Field(min_length=1)
    research_domain: Optional[ResearchDomain] = None
    gap_ids: List[str] = Field(default_factory=list)
    failure_signature: Optional[str] = None
    deterministic: bool = False
    retry_attempt: int = Field(default=0, ge=0)
    recorded_at: datetime

    @model_validator(mode="after")
    def validate_gate_attribution(self) -> "GateFailureAttribution":
        if self.recorded_at.tzinfo is None:
            raise ValueError(
                "gate failure attribution timestamps must be timezone-aware"
            )
        if len(self.gap_ids) != len(set(self.gap_ids)):
            raise ValueError("gate failure attribution gap ids must be unique")
        return self


AuditClosureStatus = Literal["completed", "cancelled", "failed"]


class TerminalAttribution(StrictModel):
    draft_id: str = Field(min_length=1)
    closure_status: AuditClosureStatus
    reason_code: str = Field(min_length=1)
    recorded_at: datetime
    delivery_bundle_id: Optional[str] = None
    gate_class: Optional[GateClass] = None


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


class DeliveryQualityGap(StrictModel):
    gap_id: str = Field(min_length=1)
    gate: Literal[
        "slot",
        "itinerary",
        "source_weather",
        "integrity",
    ]
    reason: Literal[
        "slot_option_count",
        "slot_comparison_mismatch",
        "missing_lodging_night",
        "missing_dining_day",
        "route_infeasible",
        "route_endpoint_mismatch",
        "physical_candidate_reused",
        "destination_transfer_missing",
        "day_date_discontinuity",
        "day_timeline_missing",
        "fact_not_verified",
        "source_missing",
        "weather_lineage_missing",
        "weather_unavailable_refreshable",
        "workspace_missing",
        "catalog_missing",
    ]
    field_path: str = Field(min_length=1)
    entity_id: Optional[str] = None
    candidate_id: Optional[str] = None
    worker_kind: Optional[
        Literal[
            "destination_researcher", "accommodation_researcher", "transport_researcher"
        ]
    ] = None
    repair_context: Dict[str, Any] = Field(default_factory=dict)
    gate_class: GateClass = GateClass.COMPOSITION
    research_domain: Optional[ResearchDomain] = None
    blocking: bool = True
    retry_target: Literal[
        "itinerary_planner",
        "destination_researcher",
        "accommodation_researcher",
        "transport_researcher",
        "weather_refresh",
        "candidate_gate",
        "composition_repair",
    ]


class RecommendationQualityState(StrictModel):
    schema_gate: Literal["pending", "passed", "failed"]
    candidate_gate: Literal["pending", "passed", "failed"]
    slot_gate: Literal["pending", "passed", "failed"]
    itinerary_gate: Literal["pending", "passed", "failed"]
    source_weather_gate: Literal["pending", "passed", "failed"]
    active_gap_ids: List[str] = Field(default_factory=list)


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
