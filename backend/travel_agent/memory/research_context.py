"""面向任务的 Research Packet 模型视图。

协调视图保留规划值与事实/来源引用，不重复原始证据快照；它是一种独立的上下文
契约，不是权威的 Research Packet。
"""

from __future__ import annotations

import json
import re
from datetime import timezone
from typing import Any, Dict, Literal, Mapping, Sequence

from pydantic import Field

from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.schema import StrictModel


def _packet_base(packet: ResearchPacket) -> str:
    match = re.fullmatch(r"(.+)_r(\d+)", packet.task_id)
    return match.group(1) if match else packet.task_id


def _packet_round(packet: ResearchPacket) -> int:
    match = re.fullmatch(r"(.+)_r(\d+)", packet.task_id)
    return int(match.group(2)) if match else 1

# 串行研究链中各角色能读到的上游候选种类：交通读目的地成果，
# 住宿读目的地与交通成果；目的地是第一位，没有上游。
_COORDINATION_KINDS = {
    "destination_researcher": frozenset(),
    "transport_researcher": frozenset({"visit", "dining"}),
    "accommodation_researcher": frozenset({"visit", "dining", "transport"}),
}
# 只剥离跨系统对账用的证据与约束 ID；推荐理由、取舍说明和天气敏感度
# 属于上游研究结论，保留给下游角色参考。
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
}


class CoordinationPacket(StrictModel):
    research_packet_id: str
    worker_kind: str
    candidates: list[dict[str, Any]]
    facts: list[dict[str, Any]]
    source_references: list[dict[str, Any]]


class ResearchContextView(StrictModel):
    purpose: Literal["coordination"] = "coordination"
    worker_kind: str
    destination_ids: list[str]
    coordination: list[CoordinationPacket] = Field(default_factory=list)


def _latest_round_by_base(packets: Sequence[ResearchPacket]) -> Dict[str, int]:
    """每个 Worker 基础名的最高轮次；返研后旧轮次整体退出上游视图。"""
    rounds: Dict[str, int] = {}
    for packet in packets:
        base = _packet_base(packet)
        rounds[base] = max(rounds.get(base, 0), _packet_round(packet))
    return rounds


def project_research_context(
    packets: Mapping[str, ResearchPacket],
    *,
    worker_kind: str,
    run_id: str,
    generation_id: str,
    destination_ids: Sequence[str],
) -> ResearchContextView:
    kinds = _COORDINATION_KINDS[worker_kind]
    destinations = {str(item) for item in destination_ids if str(item)}
    # 最新 packet 决定候选的可见版本。不混合不同 generation，也不为填充上下文
    # 引入无关目的地。
    in_scope = [
        packet
        for packet in packets.values()
        if packet.run_id == run_id and packet.generation_id == generation_id
    ]
    latest_rounds = _latest_round_by_base(in_scope)
    current = sorted(
        (
            packet
            for packet in in_scope
            if _packet_round(packet) == latest_rounds.get(_packet_base(packet), 0)
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
        # 保留研究者的原始排序：候选顺序本身就是相关性的表达。
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
                            "title",
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
