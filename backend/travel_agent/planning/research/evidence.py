from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import Field, model_validator

from travel_agent.planning.references import EntityRef, EntityType
from travel_agent.schema import StrictModel

FACT_SNAPSHOT_CONTRACT_VERSION = "journeypilot.fact_store_snapshot.v4"


class ProviderSnapshotProvenance(StrictModel):
    origin: Literal["live", "provider_snapshot_cache"]

    # Live retrieval does not imply production data; require an explicit environment.
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
        if self.attestation == "self":
            raise ValueError("source record cannot use self-attested evidence")
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

    @model_validator(mode="after")
    def validate_verified_sources(self) -> "FactAssertion":
        if self.status == "verified" and not any(
            link.relation == "supports" for link in self.source_links
        ):
            raise ValueError("verified fact requires a supporting source")
        return self


_SELF_ATTESTED_LOCATOR_MARKERS = (
    "user input",
    "user_input",
    "derived from user",
    "derived_from_user",
    "deterministic:",
    "journeypilot",
    "assistant",
    "model context",
)


_STABLE_IDENTITY_FIELD_PATHS = {
    "name",
    "property_name",
    "address",
    "place_id",
    "provider_place_type",
    "provider_country_code",
    "transport_class",
    "selected_mode",
    "from_endpoint",
    "to_endpoint",
}


_CONTROLLED_OR_COMPUTED_FIELDS_BY_ENTITY = {
    EntityType.LODGING_STAY: {"check_in_date", "check_out_date", "nights"},
}


_UNCERTAIN_IDENTITY_MARKERS = (
    "not verified",
    "unverified",
    "reference only",
    "placeholder",
    "unknown",
    "no verified specific",
    "未检索",
    "未确认",
    "待确认",
    "不详",
    "未確認",
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _is_self_attested_fact(fact: FactAssertion) -> bool:
    if fact.field_path in _CONTROLLED_OR_COMPUTED_FIELDS_BY_ENTITY.get(
        fact.entity_ref.entity_type,
        set(),
    ):
        return True
    return any(
        link.relation == "supports"
        and any(
            marker in link.source_locator.lower()
            for marker in _SELF_ATTESTED_LOCATOR_MARKERS
        )
        for link in fact.source_links
    )


def _is_failed_source(source: SourceRecord | None) -> bool:
    if source is None or source.lifecycle_status != "active":
        return True
    title = source.title.lower().strip()
    return (
        source.snapshot.get("error") is not None
        or source.snapshot.get("degradation_reason") is not None
        or title.endswith(" failure")
        or title.endswith(" degradation")
    )


def _is_supported_only_by_failed_sources(
    fact: FactAssertion,
    *,
    sources: Dict[str, SourceRecord],
) -> bool:
    supporting_source_ids = [
        link.source_record_id
        for link in fact.source_links
        if link.relation == "supports"
    ]
    return bool(supporting_source_ids) and all(
        _is_failed_source(sources.get(source_id)) for source_id in supporting_source_ids
    )


def _source_snapshot_contains_value(source: SourceRecord, value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    snapshot_text = json.dumps(
        source.snapshot,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    normalized_snapshot = " ".join(snapshot_text.split()).casefold()
    normalized_value = " ".join(value.split()).casefold()
    return normalized_value in normalized_snapshot


def _source_snapshot_contains_exact_scalar(source: SourceRecord, value: str) -> bool:
    expected = " ".join(value.split()).casefold()

    def contains(item: Any) -> bool:
        if isinstance(item, dict):
            return any(contains(child) for child in item.values())
        if isinstance(item, list):
            return any(contains(child) for child in item)
        return isinstance(item, str) and " ".join(item.split()).casefold() == expected

    return contains(source.snapshot)


def _source_snapshot_contains_exact_value(source: SourceRecord, value: Any) -> bool:
    expected = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    def contains(item: Any) -> bool:
        if (
            json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
            == expected
        ):
            return True
        if isinstance(item, dict):
            return any(contains(child) for child in item.values())
        if isinstance(item, list):
            return any(contains(child) for child in item)
        return False

    return contains(source.snapshot)


def _has_raw_source_value(
    fact: FactAssertion,
    *,
    sources: Dict[str, SourceRecord],
) -> bool:
    return any(
        link.relation == "supports"
        and (source := sources.get(link.source_record_id)) is not None
        and not _is_failed_source(source)
        and (
            _source_snapshot_contains_exact_scalar(source, fact.asserted_value)
            if fact.field_path == "provider_country_code"
            else _source_snapshot_contains_value(source, fact.asserted_value)
        )
        for link in fact.source_links
    )


def _source_supports_operational_value(
    source: SourceRecord, field: str, value: Any
) -> bool:
    # Bind booleans to their field; an unrelated success flag proves no booking rule.
    if isinstance(value, str):
        return _source_snapshot_contains_value(source, value)
    if isinstance(value, list):
        return bool(value) and all(
            _source_snapshot_contains_value(source, item) for item in value
        )

    def contains(item: Any) -> bool:
        if isinstance(item, dict):
            return (
                field in item
                and type(item[field]) is type(value)
                and item[field] == value
            ) or any(contains(child) for child in item.values())
        if isinstance(item, list):
            return any(contains(child) for child in item)
        return False

    return contains(source.snapshot)


def _can_verify_stable_identity_fact(
    fact: FactAssertion,
    *,
    sources: Dict[str, SourceRecord],
    as_of: datetime,
) -> bool:
    if fact.status != "stale" or fact.field_path not in _STABLE_IDENTITY_FIELD_PATHS:
        return False
    if isinstance(fact.asserted_value, str) and any(
        marker in fact.asserted_value.lower() for marker in _UNCERTAIN_IDENTITY_MARKERS
    ):
        return False
    now = _aware(as_of)
    if fact.effective_from is not None and _aware(fact.effective_from) > now:
        return False
    if any(
        boundary is not None and _aware(boundary) <= now
        for boundary in (fact.effective_to, fact.expires_at)
    ):
        return False
    supporting_sources = [
        sources.get(link.source_record_id)
        for link in fact.source_links
        if link.relation == "supports"
    ]
    return any(
        source is not None
        and source.lifecycle_status == "active"
        and (source.effective_from is None or _aware(source.effective_from) <= now)
        and all(
            boundary is None or _aware(boundary) > now
            for boundary in (source.effective_to, source.provider_valid_until)
        )
        for source in supporting_sources
    )


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
