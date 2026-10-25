from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import ConfigDict, Field, model_validator

from travel_agent.entities.candidate_discovery import CandidateDiscoveryRecord
from travel_agent.entities.candidate_intent import CandidateIntentMatch
from travel_agent.entities.candidate_ranking import CandidateRankingScore
from travel_agent.planning.research.candidates import (
    CandidateAdmissionResult,
    ResearchCandidate,
)
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.schema import StrictModel

RECOMMENDATION_CATALOG_CONTRACT_VERSION = "journeypilot.recommendation_catalog.v6"


class RecommendationCatalog(StrictModel):
    # Checkpoint reconstruction can bypass nested validation with model_construct.
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
    admission_results: List[CandidateAdmissionResult] = Field(default_factory=list)
    candidate_discovery_records: List[CandidateDiscoveryRecord] = Field(
        default_factory=list
    )
    candidate_intent_matches: List[CandidateIntentMatch] = Field(default_factory=list)
    candidate_ranking_scores: List[CandidateRankingScore] = Field(default_factory=list)

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
        keys: set[tuple[str, Optional[str]]] = set()
        candidate_index = {
            candidate.candidate_id: candidate for candidate in candidates
        }
        for admission in self.admission_results:
            candidate = candidate_index.get(admission.candidate_id)
            if candidate is None:
                raise ValueError("admission result references a missing candidate")
            if admission.evaluated_fact_revision != self.fact_data_revision:
                raise ValueError("admission result uses a different fact revision")
            if admission.evaluated_weather_revision != self.weather_data_revision:
                raise ValueError("admission result uses a different weather revision")
            key = (admission.candidate_id, admission.selection_slot_id)
            if key in keys:
                raise ValueError("candidate admission result is duplicated for a slot")
            keys.add(key)
            if admission.status == "passed" and not set(
                candidate.active_constraint_ids
            ) <= set(admission.checked_constraint_ids):
                raise ValueError(
                    "passed admission did not check every active hard constraint"
                )
            if set(admission.weather_impact_ids) != set(candidate.weather_impact_ids):
                raise ValueError(
                    "candidate weather impact lineage differs from admission"
                )
        match_keys = [
            (match.candidate_id, match.intent_id)
            for match in self.candidate_intent_matches
        ]
        if len(match_keys) != len(set(match_keys)):
            raise ValueError("candidate intent match is duplicated")
        if any(candidate_id not in candidate_index for candidate_id, _ in match_keys):
            raise ValueError("candidate intent match references a missing candidate")
        ranking_ids = [score.candidate_id for score in self.candidate_ranking_scores]
        if len(ranking_ids) != len(set(ranking_ids)):
            raise ValueError("candidate ranking score is duplicated")
        if any(candidate_id not in candidate_index for candidate_id in ranking_ids):
            raise ValueError("candidate ranking references a missing candidate")
        if any(
            score.generation_id != self.generation_id
            for score in self.candidate_ranking_scores
        ):
            raise ValueError("candidate ranking belongs to another generation")
        return self

    def candidate_index(self) -> Dict[str, ResearchCandidate]:
        return {
            candidate.candidate_id: candidate
            for packet in self.research_packets
            for candidate in packet.candidates
        }

    def admission_index(
        self,
    ) -> Dict[tuple[str, Optional[str]], CandidateAdmissionResult]:
        return {
            (result.candidate_id, result.selection_slot_id): result
            for result in self.admission_results
        }


class CandidateGateIntegrityError(RuntimeError):
    """A stale or malformed packet cannot safely enter Candidate admission."""

    def __init__(
        self, reason_code: str, message: str, *, worker_kind: str | None = None
    ):
        super().__init__(message)
        self.reason_code = reason_code
        self.worker_kind = worker_kind
