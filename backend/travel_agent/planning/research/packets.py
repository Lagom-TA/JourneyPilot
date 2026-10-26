from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal

from pydantic import ConfigDict, Field, model_validator

from travel_agent.planning.research.discovery_contracts import CandidateDiscoveryRecord
from travel_agent.planning.research.candidates import ResearchCandidate
from travel_agent.planning.research.evidence import (
    FactAssertion,
    FieldProvenance,
    SourceRecord,
)
from travel_agent.schema import StrictModel

RESEARCH_PACKET_CONTRACT_VERSION = "journeypilot.research_packet.v6"


class ResearchPacket(StrictModel):
    # checkpoint 重建出的实例也要重新校验，而不只校验新解析的 dict。
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
        # 规范化可能把候选的索引字段改写为规范值。
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

        if any(
            link.source_record_id not in source_index
            for fact in self.fact_assertions
            for link in fact.source_links
        ):
            raise ValueError(
                "research packet fact references a source outside the packet"
            )
        if not self.candidates and self.fact_assertions:
            raise ValueError("zero-candidate research packet cannot contain facts")
        if not self.candidates and self.field_provenance:
            raise ValueError(
                "zero-candidate research packet cannot contain field provenance"
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
            if not candidate_facts:
                raise ValueError(
                    "candidate requires at least one identity-bound fact assertion"
                )
            canonical_fact_ids = [fact.fact_assertion_id for fact in candidate_facts]
            canonical_field_paths = list(
                dict.fromkeys(fact.field_path for fact in candidate_facts)
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
            normalized_candidates.append(candidate)
        if normalized_candidates != self.candidates:
            object.__setattr__(self, "candidates", normalized_candidates)
        return self
