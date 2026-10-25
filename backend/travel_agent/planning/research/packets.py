from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal

from pydantic import ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from travel_agent.planning.research.discovery_contracts import CandidateDiscoveryRecord
from travel_agent.planning.references import EntityType
from travel_agent.planning.research.candidates import ResearchCandidate
from travel_agent.planning.research.evidence import (
    FactAssertion,
    FieldProvenance,
    SourceRecord,
    _can_verify_stable_identity_fact,
    _has_raw_source_value,
    _is_failed_source,
    _is_self_attested_fact,
    _is_supported_only_by_failed_sources,
    _source_snapshot_contains_exact_value,
    _source_supports_operational_value,
)
from travel_agent.schema import StrictModel

RESEARCH_PACKET_CONTRACT_VERSION = "journeypilot.research_packet.v5"


# Route on the error type; model-authored payloads can forge message text.
RESEARCH_PACKET_IDENTITY_FACTS_MISSING = "research_packet_identity_facts_missing"


class ResearchPacket(StrictModel):
    # Revalidate reconstructed checkpoint instances, not just newly parsed dicts.
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    contract_version: Literal[RESEARCH_PACKET_CONTRACT_VERSION] = (
        RESEARCH_PACKET_CONTRACT_VERSION
    )
    research_packet_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    generation_id: str = Field(min_length=1)
    intent_spec_revision: int = Field(ge=1)
    research_query_plan_id: str = Field(min_length=1)
    executed_query_ids: List[str] = Field(default_factory=list)
    candidate_discovery_records: List[CandidateDiscoveryRecord] = Field(
        default_factory=list
    )
    task_id: str = Field(min_length=1)
    worker_kind: Literal[
        "destination_researcher",
        "accommodation_researcher",
        "transport_researcher",
    ]
    constraint_pack_revision: int = Field(ge=0)
    fact_data_revision: int = Field(ge=0)
    query_context: Dict[str, Any]
    candidates: List[ResearchCandidate] = Field(default_factory=list)
    source_records: List[SourceRecord] = Field(min_length=1)
    fact_assertions: List[FactAssertion] = Field(default_factory=list)
    field_provenance: List[FieldProvenance] = Field(default_factory=list)
    generated_at: datetime

    @model_validator(mode="after")
    def normalize_and_validate_lineage(self) -> "ResearchPacket":
        # Normalization can remove facts and rewrite freshness and candidate lineage.
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("research packet candidate ids must be unique")
        discovery_candidate_ids = [
            record.candidate_id for record in self.candidate_discovery_records
        ]
        if len(discovery_candidate_ids) != len(set(discovery_candidate_ids)):
            raise ValueError("candidate discovery records must be unique")
        if set(discovery_candidate_ids) != set(candidate_ids):
            raise ValueError("every research candidate requires one discovery record")
        if any(
            record.generation_id != self.generation_id
            for record in self.candidate_discovery_records
        ):
            raise ValueError("candidate discovery record belongs to another generation")
        if any(
            not set(record.query_ids) <= set(self.executed_query_ids)
            for record in self.candidate_discovery_records
        ):
            raise ValueError("candidate discovery record names an unexecuted query")
        allowed_kinds = {
            "destination_researcher": {"visit", "dining"},
            "accommodation_researcher": {"lodging"},
            "transport_researcher": {"transport"},
        }[self.worker_kind]
        if any(
            candidate.candidate_kind not in allowed_kinds
            for candidate in self.candidates
        ):
            raise ValueError(
                "research packet contains a candidate from another worker domain"
            )

        unique_sources: Dict[str, SourceRecord] = {}
        for source in self.source_records:
            existing = unique_sources.get(source.source_record_id)
            if existing is not None and existing != source:
                raise ValueError(
                    "research packet has conflicting duplicate source records"
                )
            unique_sources.setdefault(source.source_record_id, source)
        source_index = unique_sources

        # Reject broken links before filtering; filtering must not hide malformed input.
        if any(
            link.source_record_id not in source_index
            for fact in self.fact_assertions
            for link in fact.source_links
        ):
            raise ValueError(
                "research packet fact references a source outside the packet"
            )
        removed_fact_ids = {
            fact.fact_assertion_id
            for fact in self.fact_assertions
            if _is_self_attested_fact(fact)
            or _is_supported_only_by_failed_sources(fact, sources=source_index)
        }
        removed_fact_entities = {
            fact.entity_ref.entity_id
            for fact in self.fact_assertions
            if fact.fact_assertion_id in removed_fact_ids
        }
        normalized_status_ids: set[str] = set()
        eligible_facts: List[FactAssertion] = []
        for fact in self.fact_assertions:
            if fact.fact_assertion_id in removed_fact_ids:
                continue
            if _can_verify_stable_identity_fact(
                fact,
                sources=source_index,
                as_of=self.generated_at,
            ):
                fact = fact.model_copy(update={"status": "verified"})
                normalized_status_ids.add(fact.fact_assertion_id)
            eligible_facts.append(fact)
        if not eligible_facts and self.candidates:
            raise PydanticCustomError(
                RESEARCH_PACKET_IDENTITY_FACTS_MISSING,
                "research packet requires external identity-bound facts",
            )
        if not self.candidates and eligible_facts:
            raise ValueError("zero-candidate research packet cannot contain facts")
        if not self.candidates and self.field_provenance:
            raise ValueError(
                "zero-candidate research packet cannot contain field provenance"
            )
        if removed_fact_ids or normalized_status_ids:
            object.__setattr__(self, "fact_assertions", eligible_facts)
            object.__setattr__(
                self,
                "field_provenance",
                [
                    item.model_copy(
                        update={
                            "reference_ids": [
                                reference_id
                                for reference_id in item.reference_ids
                                if reference_id not in removed_fact_ids
                            ]
                        }
                    )
                    for item in self.field_provenance
                    if any(
                        reference_id not in removed_fact_ids
                        for reference_id in item.reference_ids
                    )
                ],
            )

        unique_facts: Dict[str, FactAssertion] = {}
        for fact in self.fact_assertions:
            existing = unique_facts.get(fact.fact_assertion_id)
            if existing is not None and existing != fact:
                raise ValueError(
                    "research packet has conflicting duplicate fact assertions"
                )
            unique_facts.setdefault(fact.fact_assertion_id, fact)
        if len(unique_sources) != len(self.source_records):
            object.__setattr__(self, "source_records", list(unique_sources.values()))
        if len(unique_facts) != len(self.fact_assertions):
            object.__setattr__(self, "fact_assertions", list(unique_facts.values()))
        fact_index = unique_facts
        provenance_keys = {
            (item.entity_ref.entity_id, item.field_path)
            for item in self.field_provenance
        }
        if any(
            fact.status == "verified"
            and fact.field_path
            in {"place_id", "provider_place_type", "provider_country_code"}
            and not _has_raw_source_value(fact, sources=source_index)
            for fact in self.fact_assertions
        ):
            raise ValueError(
                "verified provider identity value must occur in a supporting external source snapshot"
            )
        if any(
            fact.status == "verified"
            and fact.entity_ref.entity_type == EntityType.TRANSPORT_LEG
            and fact.field_path
            in {
                "route_id",
                "selected_mode",
                "departure_at",
                "arrival_at",
                "duration_minutes",
                "distance_meters",
                "segments",
            }
            and not any(
                link.relation == "supports"
                and (source := source_index.get(link.source_record_id)) is not None
                and not _is_failed_source(source)
                and _source_snapshot_contains_exact_value(source, fact.asserted_value)
                for link in fact.source_links
            )
            for fact in self.fact_assertions
        ):
            raise ValueError(
                "verified transport value must exactly occur in a supporting route snapshot"
            )
        if any(
            item.origin == "external_fact"
            and not set(item.reference_ids) <= fact_index.keys()
            for item in self.field_provenance
        ):
            raise ValueError(
                "research packet provenance references a fact outside the packet"
            )
        normalized_candidates: List[ResearchCandidate] = []
        source_order = [source.source_record_id for source in self.source_records]
        for candidate in self.candidates:
            candidate_facts = [
                fact
                for fact in self.fact_assertions
                if fact.entity_ref.entity_id == candidate.candidate_id
            ]

            # Place identity alone cannot establish opening, booking, or room rules.
            operational_fields = (
                ("opening_window", "reservation_required")
                if candidate.candidate_kind in {"visit", "dining"}
                else ("room_type", "facilities")
                if candidate.candidate_kind == "lodging"
                else ()
            )
            unsupported = {}
            for field in operational_fields:
                value = getattr(candidate, field, None)
                if value is None or value == []:
                    continue
                supported = any(
                    fact.field_path == field
                    and fact.status == "verified"
                    and fact.asserted_value == value
                    and any(
                        link.relation == "supports"
                        and (source := source_index.get(link.source_record_id))
                        is not None
                        and not _is_failed_source(source)
                        and _source_supports_operational_value(source, field, value)
                        for link in fact.source_links
                    )
                    for fact in candidate_facts
                )
                if not supported:
                    unsupported[field] = [] if isinstance(value, list) else None
            if unsupported:
                candidate = candidate.model_copy(update=unsupported)
            if not candidate_facts:
                raise ValueError(
                    "candidate requires at least one identity-bound fact assertion"
                )
            canonical_fact_ids = [fact.fact_assertion_id for fact in candidate_facts]
            canonical_field_paths = list(
                dict.fromkeys(fact.field_path for fact in candidate_facts)
            )
            if any(
                not set(evaluation.fact_assertion_ids) <= set(canonical_fact_ids)
                for evaluation in candidate.constraint_evaluations
            ):
                raise ValueError(
                    "constraint evaluation references a fact outside its research packet"
                )
            fact_statuses = {fact.status for fact in candidate_facts}
            expected_freshness = (
                "current"
                if fact_statuses == {"verified"}
                else "refreshing"
                if "refreshing" in fact_statuses
                else "stale"
            )
            if candidate.freshness_status != expected_freshness:
                if candidate.candidate_id in removed_fact_entities or (
                    set(canonical_fact_ids) & normalized_status_ids
                ):
                    candidate = candidate.model_copy(
                        update={"freshness_status": expected_freshness}
                    )
                else:
                    raise ValueError(
                        "candidate freshness status must be derived from its fact assertions"
                    )
            supported_sources = {
                link.source_record_id
                for fact in candidate_facts
                for link in fact.source_links
                if link.relation == "supports"
            }
            canonical_source_ids = [
                source_id
                for source_id in source_order
                if source_id in supported_sources
            ]
            if (
                candidate.research_packet_id != self.research_packet_id
                or candidate.fact_assertion_ids != canonical_fact_ids
                or candidate.source_record_ids != canonical_source_ids
                or candidate.field_paths != canonical_field_paths
            ):
                candidate = candidate.model_copy(
                    update={
                        "research_packet_id": self.research_packet_id,
                        "fact_assertion_ids": canonical_fact_ids,
                        "source_record_ids": canonical_source_ids,
                        "field_paths": canonical_field_paths,
                    }
                )
            if any(
                (candidate.candidate_id, field_path) not in provenance_keys
                for field_path in candidate.field_paths
            ):
                raise ValueError("candidate field path lacks field provenance")
            normalized_candidates.append(candidate)
        if normalized_candidates != self.candidates:
            object.__setattr__(self, "candidates", normalized_candidates)
        return self
