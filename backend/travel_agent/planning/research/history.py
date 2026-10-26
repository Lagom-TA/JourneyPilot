from __future__ import annotations

import re
from typing import Dict, Sequence

from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.assignments import strip_round_suffix
from travel_agent.planning.nodes import RESEARCH_WORKER_NODES
from travel_agent.planning.research.candidates import ResearchCandidate
from travel_agent.planning.research.packets import ResearchPacket

_ROUND_SUFFIX = re.compile(r"_r(\d+)$")


def _latest_packets(
    packets: Dict[str, ResearchPacket], *, generation_id: str
) -> Dict[str, ResearchPacket]:
    latest: dict[str, tuple[int, ResearchPacket]] = {}
    for key, packet in packets.items():
        if packet.generation_id != generation_id:
            continue
        task_key = key.split("@", 1)[0]
        base = strip_round_suffix(task_key)
        if base not in RESEARCH_WORKER_NODES:
            continue
        match = _ROUND_SUFFIX.search(task_key)
        round_number = int(match.group(1)) if match else 1
        current = latest.get(base)
        if current is None or round_number >= current[0]:
            latest[base] = (round_number, packet)
    return {base: item[1] for base, item in latest.items()}


def _catalog_packets(state: TravelAgentState) -> list[ResearchPacket]:
    """汇总跨轮次仍然有效的候选：每个 worker 取最新 packet，并保留上一版目录中本轮未再出现的候选。"""
    if state.planning_generation is None:
        raise ValueError(
            "missing_planning_generation: candidate catalog requires a planning generation"
        )
    generation_id = state.planning_generation.generation_id
    current = _latest_packets(
        state.research_packets,
        generation_id=generation_id,
    )
    packets = [
        _packet_candidate_closure(packet, packet.candidates)
        for packet in current.values()
    ]
    previous = state.recommendation_catalog
    if (
        previous is None
        or previous.generation_id != generation_id
        or previous.fact_data_revision != state.fact_data_revision
    ):
        return packets

    current_ids_by_worker = {
        worker: {candidate.candidate_id for candidate in packet.candidates}
        for worker, packet in current.items()
    }
    current_packet_ids = {packet.research_packet_id for packet in packets}
    for packet in previous.research_packets:
        if (
            packet.worker_kind not in current
            or packet.generation_id != generation_id
            or packet.constraint_pack_revision != state.constraint_pack_revision
            or packet.fact_data_revision != state.fact_data_revision
        ):
            continue
        retained = [
            candidate
            for candidate in packet.candidates
            if candidate.candidate_id not in current_ids_by_worker[packet.worker_kind]
        ]
        if not retained or packet.research_packet_id in current_packet_ids:
            continue
        packets.append(_packet_candidate_closure(packet, retained))
        current_packet_ids.add(packet.research_packet_id)
    return packets


def _packet_candidate_closure(
    packet: ResearchPacket,
    candidates: Sequence[ResearchCandidate],
) -> ResearchPacket:
    """按候选重建 packet 的证据闭包，只保留可从候选到达的事实、来源与来源标注。"""
    if not candidates:
        return packet
    candidate_ids = {candidate.candidate_id for candidate in candidates}
    facts = [
        fact
        for fact in packet.fact_assertions
        if fact.entity_ref.entity_id in candidate_ids
    ]
    fact_ids = {fact.fact_assertion_id for fact in facts}
    source_ids = {link.source_record_id for fact in facts for link in fact.source_links}
    sources = [
        source
        for source in packet.source_records
        if source.source_record_id in source_ids
        or source.lifecycle_status == "rejected"
    ]
    provenance = [
        item.model_copy(
            update={
                "reference_ids": [
                    reference_id
                    for reference_id in item.reference_ids
                    if reference_id in fact_ids
                ]
            }
        )
        if item.origin == "external_fact"
        else item
        for item in packet.field_provenance
        if item.entity_ref.entity_id in candidate_ids
        and (
            item.origin != "external_fact"
            or any(reference_id in fact_ids for reference_id in item.reference_ids)
        )
    ]
    return ResearchPacket.model_validate(
        {
            **packet.model_dump(mode="python"),
            "candidates": list(candidates),
            "candidate_discovery_records": [
                record
                for record in packet.candidate_discovery_records
                if record.candidate_id in candidate_ids
            ],
            "source_records": sources,
            "fact_assertions": facts,
            "field_provenance": provenance,
        }
    )

