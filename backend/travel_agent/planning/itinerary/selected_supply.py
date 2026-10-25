"""Planning itinerary selected supply."""

from __future__ import annotations

from travel_agent.planning.research.candidates import DiningCandidate
from travel_agent.planning.research.candidates import LodgingCandidate
from travel_agent.planning.research.candidates import ResearchCandidate
from travel_agent.planning.research.candidates import TransportCandidate
from travel_agent.planning.research.candidates import VisitCandidate
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.planning.research.combination import candidate_coordinates
from travel_agent.planning.research.selection_contracts import CandidateSelectionPlan
from travel_agent.planning.research.selection_contracts import CandidateSelectionRole
from travel_agent.planning.research.selection_contracts import (
    SelectedCandidateCapability,
)
from travel_agent.planning.research.selection_policy import _admitted_candidate_ids


def catalog_for_candidate_selection(
    catalog: RecommendationCatalog,
    selection_plan: CandidateSelectionPlan,
) -> RecommendationCatalog:
    _validate_selection_plan_catalog(catalog, selection_plan)
    selected_ids = selection_plan.composition_candidate_ids()
    return catalog.model_copy(
        update={
            "admission_results": [
                result
                for result in catalog.admission_results
                if result.candidate_id in selected_ids
            ]
        }
    )


def catalog_for_workspace_materialization(
    catalog: RecommendationCatalog,
    selection_plan: CandidateSelectionPlan,
) -> RecommendationCatalog:
    """Keep full admitted lineage when the final Workspace crosses its contract.

    Composition uses a narrowed Catalog so an alternative cannot be placed by
    accident.  The Workspace still carries the complete Selection Plan,
    including alternatives, so materializing it against that narrowed Catalog
    falsely turns every omitted alternative into a rejected candidate.  Rebind
    to the full validated Catalog only at the Workspace boundary, after the
    composition has already been constrained and checked.
    """

    _validate_selection_plan_catalog(catalog, selection_plan)
    return catalog


def _validate_selection_plan_catalog(
    catalog: RecommendationCatalog,
    selection_plan: CandidateSelectionPlan,
) -> None:
    if selection_plan.generation_id != catalog.generation_id:
        raise ValueError("candidate selection plan belongs to another generation")
    if selection_plan.intent_spec_revision != catalog.intent_spec_revision:
        raise ValueError("candidate selection plan uses another intent revision")
    if selection_plan.catalog_revision != catalog.fact_data_revision:
        raise ValueError("candidate selection plan uses another catalog revision")
    plan_candidate_ids = {entry.candidate_id for entry in selection_plan.entries}
    if not plan_candidate_ids <= set(catalog.candidate_index()):
        raise ValueError("candidate selection plan references a missing candidate")
    if not plan_candidate_ids <= _admitted_candidate_ids(catalog):
        raise ValueError("candidate selection plan references a non-admitted candidate")


def _schedule_capabilities(candidate: ResearchCandidate) -> dict[str, object]:
    if isinstance(candidate, VisitCandidate):
        return {
            "recommended_duration_minutes": candidate.recommended_duration_minutes,
            "opening_window": candidate.opening_window,
        }
    if isinstance(candidate, DiningCandidate):
        return {
            "meal_types": list(candidate.meal_types),
            "opening_window": candidate.opening_window,
        }
    if isinstance(candidate, LodgingCandidate):
        return {
            "check_in_date": candidate.check_in_date.isoformat(),
            "check_out_date": candidate.check_out_date.isoformat(),
            "nights": candidate.nights,
        }
    assert isinstance(candidate, TransportCandidate)
    return {
        "transport_class": candidate.transport_class,
        "selected_mode": candidate.selected_mode.value,
        "departure_at": candidate.departure_at.isoformat()
        if candidate.departure_at
        else None,
        "arrival_at": candidate.arrival_at.isoformat()
        if candidate.arrival_at
        else None,
        "duration_minutes": candidate.duration_minutes,
        "from_place_id": candidate.from_endpoint.place_id,
        "to_place_id": candidate.to_endpoint.place_id,
    }


def selected_candidate_capabilities(
    *,
    catalog: RecommendationCatalog,
    selection_plan: CandidateSelectionPlan,
) -> tuple[list[SelectedCandidateCapability], list[SelectedCandidateCapability]]:
    candidates = catalog.candidate_index()
    rankings = {score.candidate_id: score for score in catalog.candidate_ranking_scores}
    coordinates = candidate_coordinates(catalog)
    selected: list[SelectedCandidateCapability] = []
    alternatives: list[SelectedCandidateCapability] = []
    for entry in selection_plan.entries:
        candidate = candidates.get(entry.candidate_id)
        ranking = rankings.get(entry.candidate_id)
        if candidate is None or ranking is None:
            raise ValueError("candidate capability is missing catalog or ranking data")
        place_id = getattr(candidate, "place_id", None)
        capability = SelectedCandidateCapability(
            candidate_id=entry.candidate_id,
            candidate_kind=candidate.candidate_kind,
            destination_id=candidate.destination_id,
            selection_role=entry.role,
            rank=entry.rank,
            matched_intent_ids=ranking.matched_intent_ids,
            unknown_intent_ids=ranking.unknown_intent_ids,
            hard_violation_intent_ids=ranking.hard_violation_intent_ids,
            selection_reasons=entry.selection_reasons,
            evidence_confidence=ranking.evidence_confidence,
            budget_fit=ranking.budget_fit,
            weather_fit=ranking.weather_fit,
            constraint_fit=ranking.constraint_fit,
            place_id=place_id,
            latitude=coordinates[entry.candidate_id][0]
            if coordinates[entry.candidate_id] is not None
            else None,
            longitude=coordinates[entry.candidate_id][1]
            if coordinates[entry.candidate_id] is not None
            else None,
            schedule_capabilities=_schedule_capabilities(candidate),
        )
        if entry.role is CandidateSelectionRole.ALTERNATIVE:
            alternatives.append(capability)
        else:
            selected.append(capability)
    return selected, alternatives
