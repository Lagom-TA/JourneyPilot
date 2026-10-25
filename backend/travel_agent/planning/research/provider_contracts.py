"""Planning research provider contracts."""

from __future__ import annotations

from datetime import date
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.provider_scope_ids import provider_evidence_scope_id
from typing import Literal
from typing import Optional


ProviderEvidenceWorkerKind = Literal[
    "destination_researcher",
    "accommodation_researcher",
    "transport_researcher",
]


ProviderEvidenceCandidateKind = Literal["visit", "dining", "lodging"]


ProviderEvidenceTransportClass = Literal[
    "long_distance",
    "public_transit",
    "flexible",
]


ProviderEvidenceStatus = Literal[
    "no_option",
    "unresolved_loss",
    "materialized",
]


ProviderRouteLegRole = Literal["outbound", "return", "inter_destination"]


TIMETABLED_TRANSPORT_CLASSES: frozenset[str] = frozenset({"long_distance"})


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderRouteLegScope(_StrictFrozenModel):
    """One exact current-Run long-distance research responsibility."""

    leg_role: ProviderRouteLegRole
    from_place_id: str = Field(min_length=1)
    to_place_id: str = Field(min_length=1)
    service_date: date
    cross_day_required: bool = False

    @model_validator(mode="after")
    def validate_endpoints(self) -> "ProviderRouteLegScope":
        if self.from_place_id == self.to_place_id:
            raise ValueError("Provider route leg requires distinct endpoints")
        return self


class ProviderEvidenceScope(_StrictFrozenModel):
    """One independently resolvable Provider research responsibility."""

    scope_id: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    run_id: str = Field(min_length=1)
    constraint_pack_revision: int = Field(ge=0)
    worker_kind: ProviderEvidenceWorkerKind
    research_domain: ResearchDomain
    candidate_kind: Optional[ProviderEvidenceCandidateKind] = None
    transport_class: Optional[ProviderEvidenceTransportClass] = None
    target_identity: Optional[str] = Field(default=None, min_length=1)
    route_leg: Optional[ProviderRouteLegScope] = None

    @model_validator(mode="after")
    def validate_dimension(self) -> "ProviderEvidenceScope":
        if self.worker_kind == "transport_researcher":
            if self.transport_class is None or self.candidate_kind is not None:
                raise ValueError(
                    "transport Provider scope requires only transport_class"
                )
            expected_domain = (
                ResearchDomain.LONG_DISTANCE_TRANSPORT
                if self.transport_class == "long_distance"
                else ResearchDomain.LOCAL_TRANSPORT
            )
            if self.research_domain != expected_domain:
                raise ValueError("transport Provider scope domain is inconsistent")
            if self.transport_class == "long_distance":
                if self.route_leg is None or self.target_identity is not None:
                    raise ValueError(
                        "long-distance Provider scope requires only exact route_leg"
                    )
            elif self.route_leg is not None or self.target_identity is None:
                raise ValueError(
                    "local transport Provider scope requires only target_identity"
                )
        else:
            if self.candidate_kind is None or self.transport_class is not None:
                raise ValueError("place Provider scope requires only candidate_kind")
            expected = {
                "visit": ResearchDomain.VISIT,
                "dining": ResearchDomain.DINING,
                "lodging": ResearchDomain.LODGING,
            }[self.candidate_kind]
            if self.research_domain != expected:
                raise ValueError("place Provider scope domain is inconsistent")
            expected_worker = (
                "accommodation_researcher"
                if self.candidate_kind == "lodging"
                else "destination_researcher"
            )
            if self.worker_kind != expected_worker:
                raise ValueError("candidate kind does not belong to Provider worker")
            if self.route_leg is not None or self.target_identity is None:
                raise ValueError("place Provider scope requires only target_identity")
        expected_scope_id = provider_evidence_scope_id(
            run_id=self.run_id,
            constraint_pack_revision=self.constraint_pack_revision,
            worker_kind=self.worker_kind,
            research_domain=self.research_domain,
            candidate_kind=self.candidate_kind,
            transport_class=self.transport_class,
            target_identity=self.target_identity,
            route_leg=self.route_leg,
        )
        if self.scope_id != expected_scope_id:
            raise ValueError("Provider evidence scope id is not authoritative")
        return self


class ProviderEvidenceAssignment(_StrictFrozenModel):
    """Server-owned assignment of one scope to a numbered worker attempt."""

    scope: ProviderEvidenceScope
    attempt_number: int = Field(ge=0)


class ProviderEvidenceOutcome(_StrictFrozenModel):
    """Current result reported for one explicit Provider-evidence scope."""

    scope: ProviderEvidenceScope
    attempt_number: int = Field(ge=0)
    provider_option_count: int = Field(ge=0)
    provider_option_materialized_count: int = Field(ge=0)
    unresolved_loss_count: int = Field(ge=0)
    status: ProviderEvidenceStatus

    @model_validator(mode="after")
    def validate_status_counts(self) -> "ProviderEvidenceOutcome":
        if self.status == "no_option" and any(
            (
                self.provider_option_count,
                self.provider_option_materialized_count,
                self.unresolved_loss_count,
            )
        ):
            raise ValueError("no-option Provider outcome must have zero counts")
        if self.status == "materialized":
            if (
                self.provider_option_materialized_count < 1
                or self.unresolved_loss_count
            ):
                raise ValueError(
                    "materialized Provider outcome requires materialized evidence"
                )
        if self.status == "unresolved_loss":
            if (
                self.unresolved_loss_count < 1
                or self.provider_option_materialized_count
            ):
                raise ValueError(
                    "unresolved Provider outcome requires only a positive loss"
                )
        return self


class ProviderEvidenceSummary(_StrictFrozenModel):
    current_scope_count: int = Field(ge=0)
    unresolved_scope_count: int = Field(ge=0)
    provider_option_count: int = Field(ge=0)
    provider_option_materialized_count: int = Field(ge=0)
    provider_salvage_loss_count: int = Field(ge=0)
