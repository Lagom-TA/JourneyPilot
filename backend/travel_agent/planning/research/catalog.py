from __future__ import annotations

from typing import Dict, List, Literal

from pydantic import ConfigDict, Field, model_validator

from travel_agent.planning.research.discovery_contracts import CandidateDiscoveryRecord
from travel_agent.planning.research.candidates import ResearchCandidate
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.schema import StrictModel

RECOMMENDATION_CATALOG_CONTRACT_VERSION = "journeypilot.recommendation_catalog.v7"


class RecommendationCatalog(StrictModel):
    # checkpoint 重建可能用 model_construct 绕过嵌套校验，因此始终重新校验实例。
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    contract_version: Literal[RECOMMENDATION_CATALOG_CONTRACT_VERSION] = (
        RECOMMENDATION_CATALOG_CONTRACT_VERSION
    )
    generation_id: str = Field(min_length=1)
    intent_spec_revision: int = Field(ge=1)
    research_query_plan_id: str = Field(min_length=1)
    fact_data_revision: int = Field(ge=0)
    weather_data_revision: int = Field(ge=0)
    research_packets: List[ResearchPacket] = Field(default_factory=list)
    candidate_discovery_records: List[CandidateDiscoveryRecord] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validate_catalog(self) -> "RecommendationCatalog":
        packet_ids = [packet.research_packet_id for packet in self.research_packets]
        if len(packet_ids) != len(set(packet_ids)):
            raise ValueError("recommendation catalog packet ids must be unique")
        candidates = [
            candidate
            for packet in self.research_packets
            for candidate in packet.candidates
        ]
        candidate_ids = [candidate.candidate_id for candidate in candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError(
                "candidate identity cannot be duplicated across research packets"
            )
        if any(
            packet.fact_data_revision != self.fact_data_revision
            for packet in self.research_packets
        ):
            raise ValueError(
                "research packet fact revision does not match recommendation catalog"
            )
        if any(
            packet.generation_id != self.generation_id
            for packet in self.research_packets
        ):
            raise ValueError(
                "research packet generation does not match recommendation catalog"
            )
        if any(
            packet.intent_spec_revision != self.intent_spec_revision
            for packet in self.research_packets
        ):
            raise ValueError("research packet intent revision does not match catalog")
        if any(
            packet.research_query_plan_id != self.research_query_plan_id
            for packet in self.research_packets
        ):
            raise ValueError("research packet query plan does not match catalog")
        discovery_by_candidate = {
            record.candidate_id: record for record in self.candidate_discovery_records
        }
        if set(discovery_by_candidate) != set(candidate_ids):
            raise ValueError("catalog discovery lineage must cover every candidate")
        if any(
            record != discovery_by_candidate.get(record.candidate_id)
            for packet in self.research_packets
            for record in packet.candidate_discovery_records
        ):
            raise ValueError("catalog discovery lineage differs from research packets")
        return self

    def candidate_index(self) -> Dict[str, ResearchCandidate]:
        return {
            candidate.candidate_id: candidate
            for packet in self.research_packets
            for candidate in packet.candidates
        }
