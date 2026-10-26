from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import Field, model_validator

from travel_agent.planning.references import EntityRef
from travel_agent.schema import StrictModel

FACT_SNAPSHOT_CONTRACT_VERSION = "journeypilot.fact_store_snapshot.v4"


class ProviderSnapshotProvenance(StrictModel):
    origin: Literal["live", "provider_snapshot_cache"]

    # 实时检索不等同于生产数据，环境必须显式声明。
    data_environment: Literal["production", "sandbox"]
    provider_name: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    cache_key_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: datetime
    retrieved_at: datetime
    provider_valid_until: Optional[datetime] = None
    cache_valid_until: datetime
    provider_contract_version: str = Field(min_length=1)
    payload_schema_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_cache_provenance(self) -> "ProviderSnapshotProvenance":
        if self.cache_valid_until <= self.retrieved_at:
            raise ValueError("provider snapshot cache validity must follow retrieval")
        if (
            self.provider_valid_until is not None
            and self.provider_valid_until < self.observed_at
        ):
            raise ValueError("provider validity cannot predate observation")
        return self


class SourceRecord(StrictModel):
    source_record_id: str = Field(min_length=1)
    source_kind: Literal["external_web", "external_tool", "rag_chunk"]
    title: str = Field(min_length=1)
    provider_name: str = Field(min_length=1)

    attestation: Literal["external", "self"] = "external"
    canonical_url: Optional[str] = None
    public_excerpt: str
    published_at: Optional[datetime] = None
    retrieved_at: datetime
    observed_at: Optional[datetime] = None
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    provider_valid_until: Optional[datetime] = None
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot: Dict[str, Any]
    lifecycle_status: Literal["active", "superseded", "withdrawn", "rejected"] = (
        "active"
    )
    tool_audit_id: Optional[str] = Field(default=None, min_length=1)
    cache_provenance: Optional[ProviderSnapshotProvenance] = None

    @model_validator(mode="after")
    def reject_self_attested_sources(self) -> "SourceRecord":
        if self.cache_provenance is not None:
            provenance = self.cache_provenance
            if provenance.provider_name != self.provider_name:
                raise ValueError(
                    "cache provenance provider does not match the source record"
                )
            if provenance.content_hash != self.content_hash:
                raise ValueError(
                    "cache provenance content hash does not match the source record"
                )
            if provenance.observed_at != self.observed_at:
                raise ValueError(
                    "cache provenance observation does not match the source record"
                )
            if provenance.retrieved_at != self.retrieved_at:
                raise ValueError(
                    "cache provenance retrieval does not match the source record"
                )
            if provenance.provider_valid_until != self.provider_valid_until:
                raise ValueError(
                    "cache provenance validity does not match the source record"
                )
        return self


class FactSourceLink(StrictModel):
    source_record_id: str = Field(min_length=1)
    relation: Literal["supports", "qualifies", "contradicts"]
    source_locator: str = Field(min_length=1)


class FactAssertion(StrictModel):
    fact_assertion_id: str = Field(min_length=1)
    entity_ref: EntityRef
    field_path: str = Field(min_length=1)
    asserted_value: Any
    unit: Optional[str] = None
    currency: Optional[str] = None
    criticality: Literal["execution_critical", "decision_critical", "auxiliary"]
    status: Literal[
        "verified", "refreshing", "stale", "conflict", "missing", "superseded"
    ]
    observed_at: Optional[datetime] = None
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    source_links: List[FactSourceLink] = Field(default_factory=list)
    supersedes_assertion_ids: List[str] = Field(default_factory=list)


class FieldProvenance(StrictModel):
    origin: Literal[
        "external_fact", "planning_decision", "deterministic_computation", "user_input"
    ]
    entity_ref: EntityRef
    field_path: str = Field(min_length=1)
    reference_ids: List[str] = Field(min_length=1)


class FactStoreSnapshot(StrictModel):
    contract_version: Literal[FACT_SNAPSHOT_CONTRACT_VERSION] = (
        FACT_SNAPSHOT_CONTRACT_VERSION
    )
    fact_data_revision: int = Field(ge=0)
    source_records: List[SourceRecord] = Field(default_factory=list)
    fact_assertions: List[FactAssertion] = Field(default_factory=list)
    field_provenance: List[FieldProvenance] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_source_links(self) -> "FactStoreSnapshot":
        source_ids = {source.source_record_id for source in self.source_records}
        assertion_ids = {fact.fact_assertion_id for fact in self.fact_assertions}
        if len(source_ids) != len(self.source_records):
            raise ValueError("fact snapshot source record ids must be unique")
        if len(assertion_ids) != len(self.fact_assertions):
            raise ValueError("fact snapshot assertion ids must be unique")
        for fact in self.fact_assertions:
            missing = {link.source_record_id for link in fact.source_links} - source_ids
            if missing:
                raise ValueError(
                    f"fact assertion references missing sources: {sorted(missing)}"
                )
        for provenance in self.field_provenance:
            if (
                provenance.origin == "external_fact"
                and not set(provenance.reference_ids) <= assertion_ids
            ):
                raise ValueError(
                    "external fact provenance references missing assertion"
                )
        return self
