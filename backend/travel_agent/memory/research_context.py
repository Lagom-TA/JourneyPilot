"""面向任务的 Research Packet 模型视图。

协调视图保留规划值与事实/来源引用，不重复原始证据快照；它是一种独立的上下文
契约，不是权威的 Research Packet。
"""

from __future__ import annotations

import json
from datetime import timezone
from typing import Any, Literal, Mapping, Sequence

from pydantic import Field

from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.schema import StrictModel

from travel_agent.planning.research.query_contracts import ResearchQuery

_COORDINATION_KINDS = {
    "destination_researcher": frozenset(),
    "accommodation_researcher": frozenset({"visit", "dining", "transport"}),
    "transport_researcher": frozenset({"visit", "dining", "lodging"}),
}
_CANDIDATE_BOOKKEEPING = {
    "research_packet_id",
    "fact_assertion_ids",
    "source_record_ids",
    "field_paths",
    "active_constraint_ids",
    "constraint_evaluations",
    "planning_decision_ids",
    "weather_impact_ids",
    "personalization_influence_ids",
    "selection_reasons",
    "tradeoff",
    "weather_sensitivity",
}


class CoordinationPacket(StrictModel):
    research_packet_id: str
    worker_kind: str
    candidates: list[dict[str, Any]]
    facts: list[dict[str, Any]]
    source_references: list[dict[str, Any]]


class ResearchContextView(StrictModel):
    contract_version: Literal["journeypilot.research_context.v1"] = (
        "journeypilot.research_context.v1"
    )
    purpose: Literal["coordination"] = "coordination"
    worker_kind: str
    destination_ids: list[str]
    coordination: list[CoordinationPacket] = Field(default_factory=list)


def project_research_context(
    packets: Mapping[str, ResearchPacket],
    *,
    worker_kind: str,
    run_id: str,
    generation_id: str,
    planned_queries: Sequence[ResearchQuery],
    assignment: Mapping[str, Any],
) -> ResearchContextView:
    kinds = _COORDINATION_KINDS[worker_kind]
    destinations = {
        query.destination_id
        for query in planned_queries
        if query.generation_id == generation_id
    }
    # 最新 packet 决定候选的可见版本。不混合不同 generation，也不为填充上下文
    # 引入无关目的地。
    current = sorted(
        (
            packet
            for packet in packets.values()
            if packet.run_id == run_id and packet.generation_id == generation_id
        ),
        key=lambda packet: (
            packet.fact_data_revision,
            packet.generated_at.replace(tzinfo=timezone.utc).timestamp()
            if packet.generated_at.tzinfo is None
            else packet.generated_at.timestamp(),
            packet.research_packet_id,
        ),
        reverse=True,
    )
    seen = set()
    view = ResearchContextView(
        worker_kind=worker_kind, destination_ids=sorted(destinations)
    )
    for packet in current:
        selected = [
            candidate
            for candidate in packet.candidates
            if candidate.candidate_id not in seen
            and candidate.destination_id in destinations
            and candidate.candidate_kind in kinds
        ]
        if not selected:
            continue
        selected.sort(key=lambda candidate: candidate.candidate_id)
        ids = {candidate.candidate_id for candidate in selected}
        seen.update(ids)
        facts = sorted(
            (
                fact
                for fact in packet.fact_assertions
                if fact.entity_ref.entity_id in ids
            ),
            key=lambda fact: fact.fact_assertion_id,
        )
        source_ids = {
            link.source_record_id for fact in facts for link in fact.source_links
        }
        view.coordination.append(
            CoordinationPacket(
                research_packet_id=packet.research_packet_id,
                worker_kind=packet.worker_kind,
                candidates=[
                    candidate.model_dump(mode="json", exclude=_CANDIDATE_BOOKKEEPING)
                    for candidate in selected
                ],
                facts=[
                    {
                        **fact.model_dump(
                            mode="json", exclude_none=True, exclude={"entity_ref"}
                        ),
                        "candidate_id": fact.entity_ref.entity_id,
                    }
                    for fact in facts
                ],
                source_references=[
                    source.model_dump(
                        mode="json",
                        exclude_none=True,
                        include={
                            "source_record_id",
                            "source_kind",
                            "provider_name",
                            "canonical_url",
                            "content_hash",
                            "published_at",
                            "retrieved_at",
                            "observed_at",
                            "effective_from",
                            "effective_to",
                            "provider_valid_until",
                            "lifecycle_status",
                        },
                    )
                    for source in sorted(
                        packet.source_records,
                        key=lambda source: source.source_record_id,
                    )
                    if source.source_record_id in source_ids
                ],
            )
        )
    view.coordination.sort(key=lambda packet: packet.research_packet_id)
    return view


def format_worker_research_context(
    packets: Mapping[str, ResearchPacket],
    **scope: Any,
) -> str:
    view = project_research_context(packets, **scope)
    return json.dumps(
        view.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
