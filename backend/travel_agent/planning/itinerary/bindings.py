from __future__ import annotations

from typing import Mapping, Optional

from travel_agent.planning.itinerary.draft import (
    AuthoredPlaceBase,
    ItineraryCompositionError,
    PhysicalPlacement,
)
from travel_agent.planning.references import EntityLineage
from travel_agent.planning.research.candidates import (
    DiningCandidate,
    ResearchCandidate,
    VisitCandidate,
)


def _lineage(
    candidate: ResearchCandidate,
    selection_slot_id: Optional[str] = None,
    *,
    additional_planning_decision_ids: Optional[list[str]] = None,
) -> EntityLineage:
    return EntityLineage(
        research_packet_id=candidate.research_packet_id,
        candidate_id=candidate.candidate_id,
        selection_slot_id=selection_slot_id,
        fact_assertion_ids=candidate.fact_assertion_ids,
        source_record_ids=candidate.source_record_ids,
        planning_decision_ids=list(
            dict.fromkeys(
                [
                    *candidate.planning_decision_ids,
                    *(additional_planning_decision_ids or []),
                ]
            )
        ),
        weather_impact_ids=candidate.weather_impact_ids,
        personalization_influence_ids=candidate.personalization_influence_ids,
    )


def _authored_lineage() -> EntityLineage:
    """The only lineage an authored entry may carry."""
    return EntityLineage(lineage_kind="authored_entity")


def _physical_place_id(candidate: ResearchCandidate) -> str:
    if isinstance(candidate, (VisitCandidate, DiningCandidate)):
        return candidate.place_id
    raise ItineraryCompositionError(
        "physical itinerary placement references another candidate kind"
    )


def _located_authored_place(placement: PhysicalPlacement) -> AuthoredPlaceBase:
    authored = placement.authored_place
    if not authored.is_located:
        raise ItineraryCompositionError(
            f"authored entry 「{authored.name}」 has no resolved map location"
        )
    return authored


def placement_place_id(
    placement: PhysicalPlacement,
    candidates: Mapping[str, ResearchCandidate],
) -> str:
    """Return the map-resolvable place id behind one physical placement."""
    if placement.candidate_id:
        candidate = candidates.get(placement.candidate_id)
        if candidate is None:
            raise ItineraryCompositionError(
                f"placement references an unadmitted candidate: {placement.candidate_id}"
            )
        return _physical_place_id(candidate)
    return _located_authored_place(placement).resolved_place_id


def _topology_place_id(
    placement: PhysicalPlacement,
    candidates: Mapping[str, ResearchCandidate],
) -> str:
    if placement.candidate_id:
        candidate = candidates.get(placement.candidate_id)
        return _physical_place_id(candidate) if candidate else ""
    return _located_authored_place(placement).resolved_place_id


def placement_display_name(
    placement: PhysicalPlacement,
    candidates: Mapping[str, ResearchCandidate],
) -> str:
    if placement.candidate_id:
        candidate = candidates[placement.candidate_id]
        if isinstance(candidate, VisitCandidate):
            return candidate.name
        if isinstance(candidate, DiningCandidate):
            return candidate.branch_name
        raise ItineraryCompositionError(
            "physical itinerary placement references another candidate kind"
        )
    return placement.authored_place.name
