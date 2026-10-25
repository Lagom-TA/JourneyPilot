from __future__ import annotations

import hashlib
from typing import Dict, Iterable, Mapping

from travel_agent.entities.candidate_intent import IntentMatchStatus
from travel_agent.entities.intent_spec import IntentStrength, IntentTarget
from travel_agent.entities.provider_evidence import (
    build_provider_evidence_assignments,
    build_required_long_distance_legs,
    explicit_cross_day_return_required,
    scope_attempt_numbers,
)
from travel_agent.entities.state import TravelAgentState
from travel_agent.planning.assignments import strip_round_suffix
from travel_agent.planning.outcomes import CandidateResearchGap, GateClass
from travel_agent.planning.research.candidates import (
    ResearchCandidate,
    TransportCandidate,
)
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.packets import ResearchPacket


def _gap_id(*parts: object) -> str:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest()[
        :18
    ]
    return f"candidate_gap_{digest}"


def _candidate_gaps(
    packet: ResearchPacket,
    candidate: ResearchCandidate,
    missing_fields: Iterable[str],
) -> list[CandidateResearchGap]:
    """Name the identity fields that keep one candidate out of the catalog."""
    return [
        CandidateResearchGap(
            gap_id=_gap_id(
                packet.worker_kind,
                candidate.candidate_id,
                "missing_comparison_fact",
                field_path,
            ),
            worker_kind=packet.worker_kind,
            generation_id=packet.generation_id,
            reason="missing_comparison_fact",
            candidate_id=candidate.candidate_id,
            field_path=field_path,
            destination_id=candidate.destination_id,
        )
        for field_path in missing_fields
    ]


def _intent_research_gaps(
    state: TravelAgentState,
    catalog: RecommendationCatalog,
    uncovered_intent_ids: Iterable[str],
) -> list[CandidateResearchGap]:
    if state.intent_spec is None or state.planning_generation is None:
        return []
    target_scope = {
        IntentTarget.VISIT: ("destination_researcher", ResearchDomain.VISIT),
        IntentTarget.DINING: ("destination_researcher", ResearchDomain.DINING),
        IntentTarget.LODGING: ("accommodation_researcher", ResearchDomain.LODGING),
        IntentTarget.LOCAL_TRANSPORT: (
            "transport_researcher",
            ResearchDomain.LOCAL_TRANSPORT,
        ),
        IntentTarget.LONG_DISTANCE_TRANSPORT: (
            "transport_researcher",
            ResearchDomain.LONG_DISTANCE_TRANSPORT,
        ),
    }
    intent_index = {
        intent.intent_id: intent for intent in state.intent_spec.active_items
    }
    destination_ids = [
        str(destination.get("place_id") or "")
        for destination in (state.controlled_trip_identity or {}).get(
            "destinations", []
        )
        if isinstance(destination, Mapping) and destination.get("place_id")
    ]
    gaps: list[CandidateResearchGap] = []
    for intent_id in sorted(set(uncovered_intent_ids)):
        intent = intent_index.get(intent_id)
        scope = target_scope.get(intent.target) if intent is not None else None
        if (
            intent is None
            or scope is None
            or (intent.strength is not IntentStrength.HARD and intent.priority < 70)
        ):
            continue
        matches = [
            match
            for match in catalog.candidate_intent_matches
            if match.intent_id == intent_id
        ]
        reason = (
            "insufficient_intent_evidence"
            if any(match.status is IntentMatchStatus.UNKNOWN for match in matches)
            else "missing_intent_candidate"
        )
        worker, domain = scope
        destination_id = destination_ids[0] if destination_ids else None
        gaps.append(
            CandidateResearchGap(
                gap_id=_gap_id(worker, reason, intent_id, destination_id or "all"),
                worker_kind=worker,
                generation_id=state.planning_generation.generation_id,
                reason=reason,
                intent_id=intent_id,
                destination_id=destination_id,
                desired_candidate_count=2,
                research_domain=domain,
            )
        )
    return gaps


def _long_distance_gaps(
    state: TravelAgentState,
    catalog: RecommendationCatalog,
    required_workers: set[str],
) -> list[CandidateResearchGap]:
    """Require each exact outbound/return long-distance responsibility."""
    if "transport_researcher" not in required_workers:
        return []
    identity = state.controlled_trip_identity or {}
    if not isinstance(identity, dict):
        return []
    legs = build_required_long_distance_legs(
        identity,
        cross_day_return_required=explicit_cross_day_return_required(
            state.user_query or ""
        ),
    )
    if not legs:
        return []

    candidate_index = catalog.candidate_index()
    admitted_scope_ids = {
        candidate.provider_evidence_scope_id
        for admission in catalog.admission_results
        if admission.status == "passed"
        and admission.selection_slot_id is None
        and isinstance(
            candidate := candidate_index[admission.candidate_id],
            TransportCandidate,
        )
        and candidate.transport_class == "long_distance"
        and candidate.provider_evidence_scope_id is not None
    }
    assignments = build_provider_evidence_assignments(
        run_id=state.run_id,
        constraint_pack_revision=state.constraint_pack_revision,
        worker_kind="transport_researcher",
        controlled_trip_identity=identity,
        prior_scope_attempts=scope_attempt_numbers(state.provider_evidence_outcomes),
        transport_classes=["long_distance"],
        long_distance_legs=legs,
    )
    return [
        CandidateResearchGap(
            gap_id=_gap_id(
                "transport_researcher",
                "missing_long_distance_anchor",
                assignment.scope.scope_id,
            ),
            worker_kind="transport_researcher",
            generation_id=state.planning_generation.generation_id,
            reason="missing_candidate",
            field_path="transport_class.long_distance",
            destination_id=assignment.scope.route_leg.to_place_id,
            provider_evidence_scope_id=assignment.scope.scope_id,
        )
        for assignment in assignments
        if assignment.scope.scope_id not in admitted_scope_ids
    ]


def _destination_coverage_gaps(
    state: TravelAgentState,
    catalog: RecommendationCatalog,
    required_workers: set[str],
) -> list[CandidateResearchGap]:
    """Require an admitted physical stop in each controlled destination."""
    planned_agents = {
        strip_round_suffix(agent) for group in state.execution_plan for agent in group
    }
    if (
        "itinerary_planner" not in planned_agents
        or "destination_researcher" not in required_workers
    ):
        return []

    candidate_index = catalog.candidate_index()
    passed = [
        candidate_index[admission.candidate_id]
        for admission in catalog.admission_results
        if admission.status == "passed" and admission.selection_slot_id is None
    ]
    physical = [
        candidate
        for candidate in passed
        if candidate.candidate_kind in {"visit", "dining"}
    ]
    gaps: list[CandidateResearchGap] = []
    destination_ids = [
        str(item.get("place_id") or "")
        for item in (state.controlled_trip_identity or {}).get("destinations", [])
        if isinstance(item, dict) and item.get("place_id")
    ]
    physical_destinations = {candidate.destination_id for candidate in physical}
    for destination_id in destination_ids:
        if destination_id in physical_destinations:
            continue
        gaps.append(
            CandidateResearchGap(
                gap_id=_gap_id(
                    "destination_researcher",
                    "missing_destination_physical_stop",
                    destination_id,
                ),
                worker_kind="destination_researcher",
                generation_id=state.planning_generation.generation_id,
                reason="missing_candidate",
                field_path="itinerary.destination_physical_stop",
                destination_id=destination_id,
            )
        )

    return gaps


def _domain_for_candidate_gap(
    gap: CandidateResearchGap,
    candidate_index: Dict[str, ResearchCandidate],
) -> ResearchDomain:
    field_path = str(gap.field_path or "")
    if field_path.startswith("candidate_kind.dining"):
        return ResearchDomain.DINING
    if field_path.startswith("candidate_kind.visit"):
        return ResearchDomain.VISIT
    if field_path.startswith("transport_class.long_distance"):
        return ResearchDomain.LONG_DISTANCE_TRANSPORT
    if field_path.startswith("itinerary.connector."):
        return ResearchDomain.LOCAL_TRANSPORT
    candidate = candidate_index.get(str(gap.candidate_id or ""))
    if candidate is not None:
        if candidate.candidate_kind == "dining":
            return ResearchDomain.DINING
        if candidate.candidate_kind == "lodging":
            return ResearchDomain.LODGING
        if candidate.candidate_kind == "transport":
            return (
                ResearchDomain.LONG_DISTANCE_TRANSPORT
                if isinstance(candidate, TransportCandidate)
                and candidate.transport_class == "long_distance"
                else ResearchDomain.LOCAL_TRANSPORT
            )
    if gap.worker_kind == "accommodation_researcher":
        return ResearchDomain.LODGING
    if gap.worker_kind == "transport_researcher":
        return ResearchDomain.LOCAL_TRANSPORT
    return ResearchDomain.VISIT


def _classify_candidate_gaps(
    gaps: Iterable[CandidateResearchGap],
    candidate_index: Dict[str, ResearchCandidate],
    *,
    prior_gaps: Iterable[CandidateResearchGap] = (),
) -> list[CandidateResearchGap]:
    prior_by_id = {gap.gap_id: gap for gap in prior_gaps}
    classified: list[CandidateResearchGap] = []
    for gap in gaps:
        prior = prior_by_id.get(gap.gap_id)
        classified.append(
            gap.model_copy(
                update={
                    "gate_class": GateClass.COMPOSITION,
                    "research_domain": _domain_for_candidate_gap(gap, candidate_index),
                    "status": prior.status if prior is not None else gap.status,
                    "attempted_signatures": list(
                        dict.fromkeys(
                            [
                                *(
                                    prior.attempted_signatures
                                    if prior is not None
                                    else []
                                ),
                                *gap.attempted_signatures,
                            ]
                        )
                    ),
                }
            )
        )
    return classified
