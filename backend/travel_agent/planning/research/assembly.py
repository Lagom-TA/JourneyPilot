from __future__ import annotations

import logging
from typing import Iterable, Mapping

from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.outcomes import CandidateResearchGap
from travel_agent.planning.research.candidates import ResearchCandidate
from travel_agent.planning.research.catalog import (
    CandidateGateIntegrityError,
    RecommendationCatalog,
)
from travel_agent.planning.research.gaps import _candidate_gaps
from travel_agent.planning.research.history import (
    _apply_candidate_caps,
    _catalog_packets,
)
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.planning.research.requirements import (
    _destination_country_codes,
    _destination_points,
)
from travel_agent.planning.weather.candidates import _target_ref, _weather_days
from travel_agent.planning.weather.models import WeatherImpact
from travel_agent.planning.research.admission.assessment import admit_candidate
from travel_agent.planning.research.admission.lodging import normalize_lodging_price_evidence
from travel_agent.planning.requirements.constraint_applicability import bind_candidate_constraint_gate_attestations
from travel_agent.planning.weather.impacts import WeatherImpactEngine, risk_profile_from_constraint_pack

logger = logging.getLogger(__name__)


def build_candidate_catalog(
    state: TravelAgentState,
    *,
    packets: Iterable[ResearchPacket] | None = None,
) -> tuple[RecommendationCatalog, list[WeatherImpact], list[CandidateResearchGap]]:
    """Build a deterministic catalog from current packets and Gate-owned observations."""

    packets = list(packets) if packets is not None else _catalog_packets(state)
    if state.planning_generation is None:
        raise CandidateGateIntegrityError(
            "missing_planning_generation",
            "candidate catalog requires a planning generation",
        )
    if state.intent_spec is None or state.research_query_plan is None:
        raise CandidateGateIntegrityError(
            "missing_intent_research_contract",
            "candidate catalog requires IntentSpec and ResearchQueryPlan",
        )
    if (
        state.research_query_plan.generation_id
        != state.planning_generation.generation_id
        or state.research_query_plan.intent_spec_revision != state.intent_spec_revision
    ):
        raise CandidateGateIntegrityError(
            "stale_research_query_plan",
            "candidate catalog received a stale ResearchQueryPlan",
        )
    packets = _apply_candidate_caps(
        packets,
        state.research_query_plan.per_domain_candidate_caps,
    )
    generation_id = state.planning_generation.generation_id
    risk_profile = risk_profile_from_constraint_pack(state.constraint_pack)
    engine = WeatherImpactEngine()
    updated_packets: list[ResearchPacket] = []
    admissions = []
    impacts: list[WeatherImpact] = []
    gaps: list[CandidateResearchGap] = []
    destination_country_codes = _destination_country_codes(state)
    controlled_destination_points = _destination_points(state)
    hard_constraints = (
        state.constraint_pack.get("hard_constraints") or []
        if isinstance(state.constraint_pack, Mapping)
        else []
    )

    for packet in packets:
        worker = packet.worker_kind
        if packet.generation_id != generation_id:
            raise CandidateGateIntegrityError(
                "stale_planning_generation",
                f"{worker} packet belongs to another planning generation",
                worker_kind=worker,
            )
        if packet.constraint_pack_revision != state.constraint_pack_revision:
            raise CandidateGateIntegrityError(
                "stale_constraint_revision",
                f"{worker} packet uses stale constraint revision",
                worker_kind=worker,
            )
        if packet.fact_data_revision != state.fact_data_revision:
            raise CandidateGateIntegrityError(
                "stale_fact_revision",
                f"{worker} packet uses stale fact revision",
                worker_kind=worker,
            )
        packet = _normalize_lodging_price_evidence(packet)
        packet = bind_candidate_constraint_gate_attestations(
            packet,
            constraint_pack=state.constraint_pack,
        )
        updated_candidates: list[ResearchCandidate] = []
        for candidate in packet.candidates:
            candidate_facts = [
                fact
                for fact in packet.fact_assertions
                if fact.entity_ref.entity_id == candidate.candidate_id
            ]
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
            admission = admit_candidate(
                candidate,
                fact_data_revision=state.fact_data_revision,
                weather_data_revision=(
                    state.weather_context.weather_data_revision
                    if state.weather_context
                    else 0
                ),
                weather_impacts=candidate_impacts,
                weather_evaluated_dates=[
                    day.date for day in days if day.data_kind != "unavailable"
                ],
                expected_destination_country_code=destination_country_codes.get(
                    candidate.destination_id
                ),
                destination_point=controlled_destination_points.get(
                    candidate.destination_id
                ),
                identity_fact_values={
                    field_path: [
                        fact.asserted_value
                        for fact in candidate_facts
                        if fact.field_path == field_path
                    ]
                    for field_path in {fact.field_path for fact in candidate_facts}
                },
                hard_constraints=hard_constraints,
                candidate_facts=candidate_facts,
                source_records=packet.source_records,
            )
            admissions.append(admission)
            logger.info(
                "Candidate admission | worker=%s candidate=%s kind=%s status=%s "
                "missing=%s budget_fit=%.2f constraint_fit=%.2f",
                worker,
                candidate.candidate_id,
                candidate.candidate_kind,
                admission.status,
                ",".join(admission.missing_field_paths) or "-",
                admission.fit_scores.budget_fit,
                admission.fit_scores.constraint_fit,
            )
            gaps.extend(
                _candidate_gaps(packet, candidate, admission.missing_field_paths)
            )
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
        admission_results=admissions,
        candidate_discovery_records=[
            record
            for packet in updated_packets
            for record in packet.candidate_discovery_records
        ],
    )
    return (
        catalog,
        list({item.weather_impact_id: item for item in impacts}.values()),
        gaps,
    )


def _normalize_lodging_price_evidence(packet: ResearchPacket) -> ResearchPacket:
    """Normalize every lodging price before Candidate Gate attests it."""

    candidates: list[ResearchCandidate] = []
    changed = False
    for candidate in packet.candidates:
        normalized = normalize_lodging_price_evidence(
            candidate,
            candidate_facts=[
                fact
                for fact in packet.fact_assertions
                if fact.entity_ref.entity_id == candidate.candidate_id
            ],
            source_records=packet.source_records,
        )
        changed = changed or normalized != candidate
        candidates.append(normalized)
    return packet.model_copy(update={"candidates": candidates}) if changed else packet
