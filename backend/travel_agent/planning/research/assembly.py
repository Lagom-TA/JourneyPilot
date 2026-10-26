from __future__ import annotations

import logging
from typing import Iterable

from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.research.candidates import ResearchCandidate
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.planning.research.history import _catalog_packets
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.planning.weather.candidates import _target_ref, _weather_days
from travel_agent.planning.weather.models import WeatherImpact
from travel_agent.planning.weather.impacts import WeatherImpactEngine, risk_profile_from_constraint_pack

logger = logging.getLogger(__name__)


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
    if state.intent_spec is None or state.research_query_plan is None:
        raise ValueError(
            "missing_intent_research_contract: candidate catalog requires "
            "IntentSpec and ResearchQueryPlan"
        )
    if (
        state.research_query_plan.generation_id
        != state.planning_generation.generation_id
        or state.research_query_plan.intent_spec_revision != state.intent_spec_revision
    ):
        raise ValueError(
            "stale_research_query_plan: candidate catalog received a stale ResearchQueryPlan"
        )
    generation_id = state.planning_generation.generation_id
    risk_profile = risk_profile_from_constraint_pack(state.constraint_pack)
    engine = WeatherImpactEngine()
    updated_packets: list[ResearchPacket] = []
    impacts: list[WeatherImpact] = []

    for packet in packets:
        worker = packet.worker_kind
        if packet.generation_id != generation_id:
            raise ValueError(
                f"stale_planning_generation: {worker} packet belongs to another "
                "planning generation"
            )
        if packet.constraint_pack_revision != state.constraint_pack_revision:
            raise ValueError(
                f"stale_constraint_revision: {worker} packet uses stale constraint revision"
            )
        if packet.fact_data_revision != state.fact_data_revision:
            raise ValueError(
                f"stale_fact_revision: {worker} packet uses stale fact revision"
            )
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
        intent_spec_revision=state.intent_spec_revision,
        research_query_plan_id=state.research_query_plan.query_plan_id,
        fact_data_revision=state.fact_data_revision,
        weather_data_revision=(
            state.weather_context.weather_data_revision if state.weather_context else 0
        ),
        research_packets=updated_packets,
        candidate_discovery_records=[
            record
            for packet in updated_packets
            for record in packet.candidate_discovery_records
        ],
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
