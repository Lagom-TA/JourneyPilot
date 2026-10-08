"""Task-scoped model views of durable Research Packets.

Coordination keeps planning values and fact/source references, without repeating
raw evidence snapshots. Targeted repairs keep the full selected lineage closure.
The result is a separate context contract, never an admitted Research Packet.
"""

from __future__ import annotations

import json
from datetime import timezone
from typing import Any, Literal, Mapping, Sequence

from pydantic import Field

from ..entities.contract_base import StrictModel
from ..entities.delivery_bundle import CandidateResearchGap, ResearchPacket
from ..entities.research_query_plan import ResearchQuery

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
    "constraint_gate_attestation",
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
    purpose: Literal["coordination_and_repair"] = "coordination_and_repair"
    worker_kind: str
    destination_ids: list[str]
    coordination: list[CoordinationPacket] = Field(default_factory=list)
    repair_packets: list[dict[str, Any]] = Field(default_factory=list)


def _closure(packet: ResearchPacket, candidate_ids: set[str]) -> dict[str, Any]:
    candidates = [
        candidate
        for candidate in packet.candidates
        if candidate.candidate_id in candidate_ids
    ]
    # Include every fact on the selected entities, including missing/contradictory
    # fields needed by a repair, not just the candidate's supporting index.
    facts = [
        fact
        for fact in packet.fact_assertions
        if fact.entity_ref.entity_id in candidate_ids
    ]
    source_ids = {
        source_id
        for candidate in candidates
        for source_id in candidate.source_record_ids
    }
    source_ids.update(
        link.source_record_id for fact in facts for link in fact.source_links
    )
    payload = packet.model_dump(mode="json", exclude_none=True)
    payload.update(
        candidates=[
            candidate.model_dump(mode="json", exclude_none=True)
            for candidate in candidates
        ],
        fact_assertions=[
            fact.model_dump(mode="json", exclude_none=True) for fact in facts
        ],
        source_records=[
            source.model_dump(mode="json", exclude_none=True)
            for source in packet.source_records
            if source.source_record_id in source_ids
        ],
        field_provenance=[
            item.model_dump(mode="json", exclude_none=True)
            for item in packet.field_provenance
            if item.entity_ref.entity_id in candidate_ids
        ],
        candidate_discovery_records=[
            item.model_dump(mode="json", exclude_none=True)
            for item in packet.candidate_discovery_records
            if item.candidate_id in candidate_ids
        ],
    )
    # Query prose/provider options are already in the authoritative assignment;
    # they are not part of an entity's fact/source closure.
    payload.pop("query_context", None)
    return payload


def project_research_context(
    packets: Mapping[str, ResearchPacket],
    *,
    worker_kind: str,
    run_id: str,
    generation_id: str,
    planned_queries: Sequence[ResearchQuery],
    assignment: Mapping[str, Any],
    gaps: Sequence[CandidateResearchGap] = (),
) -> ResearchContextView:
    kinds = _COORDINATION_KINDS[worker_kind]
    destinations = {
        query.destination_id
        for query in planned_queries
        if query.generation_id == generation_id
    }
    explicit_repair_ids = set(assignment.get("excluded_candidate_ids") or [])
    repair_ids = set(explicit_repair_ids)
    query_ids = {
        query.query_id
        for query in planned_queries
        if query.generation_id == generation_id
    }
    repair_ids.update(
        gap.candidate_id
        for gap in gaps
        if gap.candidate_id
        and gap.worker_kind == worker_kind
        and gap.generation_id == generation_id
        and gap.status in {"open", "researching"}
        and (gap.query_id is None or gap.query_id in query_ids)
        and (gap.destination_id is None or gap.destination_id in destinations)
    )
    # Newest packet owns a candidate's visible revision. Never mix generations
    # or introduce unrelated destinations merely to fill the context.
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
            and (
                candidate.destination_id in destinations
                or candidate.candidate_id in explicit_repair_ids
            )
            and (
                candidate.candidate_kind in kinds
                or candidate.candidate_id in repair_ids
            )
        ]
        if not selected:
            continue
        selected.sort(key=lambda candidate: candidate.candidate_id)
        ids = {candidate.candidate_id for candidate in selected}
        seen.update(ids)
        repair = ids & repair_ids if packet.worker_kind == worker_kind else set()
        if repair:
            view.repair_packets.append(_closure(packet, repair))
        coordination = [
            candidate for candidate in selected if candidate.candidate_id not in repair
        ]
        if not coordination:
            continue
        ids = {candidate.candidate_id for candidate in coordination}
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
                    for candidate in coordination
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
    view.repair_packets.sort(key=lambda packet: packet["research_packet_id"])
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
