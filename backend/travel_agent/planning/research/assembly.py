from __future__ import annotations

import hashlib
import logging
from typing import Iterable

from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.research.candidates import ResearchCandidate
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.planning.research.evidence import FactAssertion, SourceRecord
from travel_agent.planning.research.history import _catalog_packets
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.planning.weather.candidates import _target_ref, _weather_days
from travel_agent.planning.weather.models import WeatherImpact
from travel_agent.planning.weather.impacts import WeatherImpactEngine, risk_profile_from_constraint_pack

logger = logging.getLogger(__name__)


def _merge_parallel_packets(packets: list[ResearchPacket]) -> list[ResearchPacket]:
    """为冲突的局部编号分配稳定身份，并合并相同知识片段。"""
    candidate_ids: set[str] = set()
    fact_ids: dict[str, FactAssertion] = {}
    sources: dict[str, SourceRecord] = {}
    result: list[ResearchPacket] = []
    for packet in sorted(packets, key=lambda item: item.research_packet_id):
        def replacement(kind: str, value: str) -> str:
            digest = hashlib.sha256(
                f"{packet.research_packet_id}\0{value}".encode()
            ).hexdigest()[:20]
            return f"{kind}_{digest}"

        renamed = {
            candidate.candidate_id: replacement("candidate", candidate.candidate_id)
            for candidate in packet.candidates if candidate.candidate_id in candidate_ids
        }
        candidates = [candidate.model_copy(update={
            "candidate_id": renamed.get(candidate.candidate_id, candidate.candidate_id)
        }) for candidate in packet.candidates]
        for candidate in candidates:
            if candidate.candidate_id in candidate_ids:
                raise ValueError("候选身份冲突")
            candidate_ids.add(candidate.candidate_id)
        assertions = []
        renamed_facts = {}
        for fact in packet.fact_assertions:
            entity = fact.entity_ref.model_copy(update={
                "entity_id": renamed.get(fact.entity_ref.entity_id, fact.entity_ref.entity_id)
            })
            fact = fact.model_copy(update={"entity_ref": entity})
            previous = fact_ids.get(fact.fact_assertion_id)
            if previous is not None and previous != fact:
                old_id = fact.fact_assertion_id
                new_id = replacement("fact", old_id)
                if new_id in fact_ids:
                    raise ValueError("事实身份冲突")
                renamed_facts[old_id] = new_id
                fact = fact.model_copy(update={"fact_assertion_id": new_id})
            fact_ids[fact.fact_assertion_id] = fact
            assertions.append(fact)
        candidates = [candidate.model_copy(update={
            "constraint_evaluations": [evaluation.model_copy(update={
                "fact_assertion_ids": [renamed_facts.get(item, item) for item in evaluation.fact_assertion_ids]
            }) for evaluation in candidate.constraint_evaluations]
        }) for candidate in candidates]
        assertions = [fact.model_copy(update={
            "supersedes_assertion_ids": [renamed_facts.get(item, item) for item in fact.supersedes_assertion_ids]
        }) for fact in assertions]
        provenance = [item.model_copy(update={
            "entity_ref": item.entity_ref.model_copy(update={
                "entity_id": renamed.get(item.entity_ref.entity_id, item.entity_ref.entity_id)
            }),
            "reference_ids": [renamed_facts.get(ref, ref) for ref in item.reference_ids]
            if item.origin == "external_fact" else item.reference_ids,
        }) for item in packet.field_provenance]
        packet_sources = []
        for source in packet.source_records:
            previous = sources.get(source.source_record_id)
            if previous is not None and previous != source:
                same = (
                    previous.source_kind == source.source_kind == "rag_chunk"
                    and previous.title == source.title
                    and previous.provider_name == source.provider_name
                    and previous.canonical_url == source.canonical_url
                    and previous.published_at == source.published_at
                    and previous.lifecycle_status == source.lifecycle_status
                    and previous.snapshot.get("content") == source.snapshot.get("content")
                    and previous.snapshot.get("source") == source.snapshot.get("source")
                    and previous.snapshot.get("collection") == source.snapshot.get("collection")
                    and previous.snapshot.get("metadata") == source.snapshot.get("metadata")
                )
                if not same:
                    raise ValueError("来源身份冲突")
                source = previous
            sources[source.source_record_id] = source
            packet_sources.append(source)
        result.append(ResearchPacket.model_validate({
            **packet.model_dump(mode="python"), "candidates": candidates,
            "fact_assertions": assertions, "field_provenance": provenance,
            "source_records": packet_sources,
        }))
    return result


def build_candidate_catalog(
    state: TravelAgentState,
    *,
    packets: Iterable[ResearchPacket] | None = None,
) -> tuple[RecommendationCatalog, list[WeatherImpact]]:
    """把当前 worker packet 汇总为确定性的候选目录，并计算各候选的天气影响。"""
    packets = list(packets) if packets is not None else _catalog_packets(state)
    if state.planning_generation is None:
        raise ValueError(
            "missing_planning_generation: candidate catalog requires a planning generation"
        )
    generation_id = state.planning_generation.generation_id
    for packet in packets:
        if packet.run_id != state.run_id:
            raise ValueError(f"stale_run: {packet.worker_kind} packet belongs to another run")
        if packet.generation_id != generation_id:
            raise ValueError(
                f"stale_planning_generation: {packet.worker_kind} packet belongs to another "
                "planning generation"
            )
        if packet.fact_data_revision != state.fact_data_revision:
            raise ValueError(
                f"stale_fact_revision: {packet.worker_kind} packet uses stale fact revision"
            )
    packets = _merge_parallel_packets(packets)
    risk_profile = risk_profile_from_constraint_pack(state.constraint_pack)
    engine = WeatherImpactEngine()
    updated_packets: list[ResearchPacket] = []
    impacts: list[WeatherImpact] = []

    for packet in packets:
        updated_candidates: list[ResearchCandidate] = []
        for candidate in packet.candidates:
            candidate_impacts: list[WeatherImpact] = []
            days = _weather_days(state, candidate)
            for day in days:
                candidate_impacts.extend(
                    engine.evaluate(
                        weather_day=day,
                        target_ref=_target_ref(candidate),
                        sensitivity=candidate.weather_sensitivity,
                        risk_profile=risk_profile,
                    )
                )
            candidate = candidate.model_copy(
                update={
                    "weather_impact_ids": [
                        impact.weather_impact_id for impact in candidate_impacts
                    ]
                }
            )
            updated_candidates.append(candidate)
            impacts.extend(candidate_impacts)
        updated_packets.append(
            packet.model_copy(update={"candidates": updated_candidates})
        )

    catalog = RecommendationCatalog(
        generation_id=generation_id,
        fact_data_revision=state.fact_data_revision,
        weather_data_revision=(
            state.weather_context.weather_data_revision if state.weather_context else 0
        ),
        research_packets=updated_packets,
    )
    logger.info(
        "Candidate catalog built | packets=%d candidates=%d",
        len(updated_packets),
        sum(len(packet.candidates) for packet in updated_packets),
    )
    return (
        catalog,
        list({item.weather_impact_id: item for item in impacts}.values()),
    )
