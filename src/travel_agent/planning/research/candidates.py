from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from typing import Annotated, Dict, List, Literal, Optional, Union

from pydantic import Field, model_validator

from travel_agent.planning.transport import (
    TransportEndpoint,
    TransportMode,
    TransportSegment,
)
from travel_agent.planning.weather.models import WeatherSensitivity
from travel_agent.schema import StrictModel


class CandidateConstraintEvaluation(StrictModel):
    constraint_id: str = Field(min_length=1)
    status: Literal["passed", "failed", "unknown"]
    fact_assertion_ids: List[str] = Field(default_factory=list)
    reason_code: Optional[str] = None

    @model_validator(mode="after")
    def validate_evidence(self) -> "CandidateConstraintEvaluation":
        if self.status in {"passed", "failed"} and not self.fact_assertion_ids:
            raise ValueError("decided constraint evaluation requires supporting facts")
        if self.status in {"failed", "unknown"} and self.reason_code is None:
            object.__setattr__(
                self,
                "reason_code",
                "missing_evidence"
                if self.status == "unknown"
                else "hard_constraint_failed",
            )
        return self


class CandidateConstraintGateAttestation(StrictModel):
    # Only the server gate attests which authoritative inputs it evaluated.
    schema_version: Literal["candidate_constraint_gate.v1"] = (
        "candidate_constraint_gate.v1"
    )
    run_id: str = Field(min_length=1)
    research_packet_id: str = Field(min_length=1)
    worker_kind: Literal[
        "destination_researcher", "accommodation_researcher", "transport_researcher"
    ]
    candidate_id: str = Field(min_length=1)
    fact_data_revision: int = Field(ge=0)
    scoped_constraint_fingerprint: str = Field(
        min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$"
    )
    candidate_facts_fingerprint: str = Field(
        min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$"
    )
    evaluation_fingerprint: str = Field(
        min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$"
    )


class CandidateBase(StrictModel):
    candidate_id: str = Field(min_length=1)
    research_packet_id: str = Field(min_length=1)
    destination_id: str = Field(min_length=1)
    fact_assertion_ids: List[str] = Field(min_length=1)
    source_record_ids: List[str] = Field(min_length=1)
    field_paths: List[str] = Field(min_length=1)
    active_constraint_ids: List[str] = Field(default_factory=list)
    constraint_evaluations: List[CandidateConstraintEvaluation] = Field(
        default_factory=list
    )

    constraint_gate_attestation: Optional[CandidateConstraintGateAttestation] = None
    weather_sensitivity: WeatherSensitivity
    selection_reasons: List[str] = Field(min_length=2, max_length=3)
    tradeoff: str = Field(min_length=1)
    planning_decision_ids: List[str] = Field(default_factory=list)
    weather_impact_ids: List[str] = Field(default_factory=list)
    personalization_influence_ids: List[str] = Field(default_factory=list)
    freshness_status: Literal["current", "refreshing", "stale"]
    observed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_candidate_gate_inputs(self) -> "CandidateBase":
        if len(self.active_constraint_ids) != len(set(self.active_constraint_ids)):
            raise ValueError("active candidate constraint ids must be unique")
        evaluation_ids = [item.constraint_id for item in self.constraint_evaluations]
        if len(evaluation_ids) != len(set(evaluation_ids)):
            raise ValueError("candidate constraint evaluations must be unique")
        if not set(evaluation_ids) <= set(self.active_constraint_ids):
            raise ValueError("candidate cannot evaluate an inactive hard constraint")
        if any(
            not set(item.fact_assertion_ids) <= set(self.fact_assertion_ids)
            for item in self.constraint_evaluations
        ):
            raise ValueError("constraint evaluation facts must belong to the candidate")
        return self


class VisitCandidate(CandidateBase):
    candidate_kind: Literal["visit"] = "visit"
    place_id: str = Field(min_length=1)
    provider_place_type: str = Field(min_length=1)
    provider_country_code: str = Field(
        min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$"
    )
    name: str = Field(min_length=1)
    address: str = Field(min_length=1)
    visit_type: Literal[
        "attraction", "experience", "culture", "shopping", "nature", "other"
    ]
    recommended_duration_minutes: int = Field(ge=1)
    estimated_cost_cny: Optional[float] = Field(default=None, ge=0)
    opening_window: Optional[str] = None
    reservation_required: Optional[bool] = None

    # Leave unsupported descriptive claims empty rather than requiring invention.
    highlights: List[str] = Field(default_factory=list)


class DiningCandidate(CandidateBase):
    candidate_kind: Literal["dining"] = "dining"
    place_id: str = Field(min_length=1)
    provider_place_type: str = Field(min_length=1)
    provider_country_code: str = Field(
        min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$"
    )
    branch_name: str = Field(min_length=1)
    address: str = Field(min_length=1)
    meal_types: List[Literal["breakfast", "lunch", "dinner", "snack", "other"]] = Field(
        min_length=1
    )

    cuisine_types: List[str] = Field(default_factory=list)
    average_spend_cny: Optional[float] = Field(default=None, ge=0)
    recommended_dishes: List[str] = Field(default_factory=list)
    opening_window: Optional[str] = None
    reservation_required: Optional[bool] = None
    availability_status: Literal["confirmed", "needs_confirmation", "unavailable"]


class LodgingCandidate(CandidateBase):
    candidate_kind: Literal["lodging"] = "lodging"
    place_id: str = Field(min_length=1)
    provider_place_type: str = Field(min_length=1)
    provider_country_code: str = Field(
        min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$"
    )
    property_name: str = Field(min_length=1)
    address: str = Field(min_length=1)
    check_in_date: Date
    check_out_date: Date
    nights: int = Field(ge=1)
    room_type: Optional[str] = None
    nightly_price_cny: Optional[float] = Field(default=None, ge=0)
    total_price_cny: Optional[float] = Field(default=None, ge=0)
    price_kind: Literal["reference_estimate", "live_quote"] = "reference_estimate"
    facilities: List[str] = Field(default_factory=list)
    anchor_travel_minutes: Dict[str, int] = Field(default_factory=dict)
    availability_status: Literal["confirmed", "needs_confirmation", "unavailable"]

    @model_validator(mode="after")
    def validate_stay(self) -> "LodgingCandidate":
        expected = (self.check_out_date - self.check_in_date).days
        if expected < 1 or self.nights != expected:
            raise ValueError(
                "candidate nights must equal check-out date minus check-in date"
            )
        if (
            self.price_kind == "reference_estimate"
            and self.availability_status == "confirmed"
        ):
            raise ValueError(
                "reference_estimate lodging cannot be availability confirmed; "
                "use needs_confirmation or a live_quote"
            )
        return self


class TransportCandidate(CandidateBase):
    candidate_kind: Literal["transport"] = "transport"
    route_id: str = Field(min_length=1)
    transport_class: Literal["long_distance", "public_transit", "flexible"]
    provider_evidence_scope_id: Optional[str] = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    selected_mode: TransportMode
    from_endpoint: TransportEndpoint
    to_endpoint: TransportEndpoint
    departure_at: Optional[datetime] = None
    arrival_at: Optional[datetime] = None
    duration_minutes: int = Field(ge=0)
    distance_meters: Optional[int] = Field(default=None, ge=0)
    total_cost_cny: Optional[float] = Field(default=None, ge=0)
    segments: List[TransportSegment] = Field(min_length=1)
    booking_status: Literal[
        "not_required", "recommended", "required", "booked", "unknown"
    ]

    @model_validator(mode="after")
    def validate_segments(self) -> "TransportCandidate":
        if (
            self.transport_class == "long_distance"
            and self.provider_evidence_scope_id is None
        ):
            raise ValueError(
                "long-distance candidate requires exact Provider evidence scope"
            )
        if (
            self.transport_class != "long_distance"
            and self.provider_evidence_scope_id is not None
        ):
            raise ValueError(
                "local transport candidate cannot carry long-distance scope"
            )
        if self.segments[0].from_endpoint != self.from_endpoint:
            raise ValueError("transport candidate first segment must match origin")
        if self.segments[-1].to_endpoint != self.to_endpoint:
            raise ValueError("transport candidate last segment must match destination")
        return self


ResearchCandidate = Annotated[
    Union[VisitCandidate, DiningCandidate, LodgingCandidate, TransportCandidate],
    Field(discriminator="candidate_kind"),
]


class CandidateFitScores(StrictModel):
    budget_fit: float = Field(default=1.0, ge=0.0, le=1.0)
    weather_fit: float = Field(default=1.0, ge=0.0, le=1.0)
    constraint_fit: float = Field(default=1.0, ge=0.0, le=1.0)


class CandidateAdmissionResult(StrictModel):
    candidate_id: str = Field(min_length=1)
    selection_slot_id: Optional[str] = None
    status: Literal["passed", "insufficient_for_admission"]
    checked_constraint_ids: List[str] = Field(default_factory=list)
    missing_field_paths: List[str] = Field(default_factory=list)
    fit_scores: CandidateFitScores = Field(default_factory=CandidateFitScores)
    evaluated_fact_revision: int = Field(ge=0)
    evaluated_weather_revision: int = Field(ge=0)
    weather_impact_ids: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_outcome(self) -> "CandidateAdmissionResult":
        if self.status == "passed" and self.missing_field_paths:
            raise ValueError("passed admission cannot contain missing-field reasons")
        if self.status == "insufficient_for_admission" and not self.missing_field_paths:
            raise ValueError("insufficient admission requires missing field paths")
        return self
