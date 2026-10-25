from __future__ import annotations

from typing import Any, Dict

from travel_agent.entities.candidate_selection import CandidateSelectionPlan
from travel_agent.planning.research.candidates import (
    DiningCandidate,
    LodgingCandidate,
    TransportCandidate,
    VisitCandidate,
)
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.services.candidate_selection import (
    selected_candidate_capabilities,
)


def selected_ids_by_kind(
    catalog: RecommendationCatalog,
    *,
    skeleton_only: bool = False,
) -> Dict[str, list[str]]:
    """List selected candidate ids per domain, ordered by descending fit."""
    candidate_index = catalog.candidate_index()
    fit_by_id: Dict[str, float] = {}
    for result in catalog.admission_results:
        if result.status != "passed" or result.candidate_id not in candidate_index:
            continue
        scores = result.fit_scores
        fit = min(scores.budget_fit, scores.weather_fit, scores.constraint_fit)
        fit_by_id[result.candidate_id] = min(
            fit_by_id.get(result.candidate_id, 1.0), fit
        )
    return {
        kind: sorted(
            (
                candidate_id
                for candidate_id in fit_by_id
                if candidate_index[candidate_id].candidate_kind == kind
                and not (
                    skeleton_only
                    and kind == "transport"
                    and isinstance(candidate_index[candidate_id], TransportCandidate)
                    and candidate_index[candidate_id].transport_class != "long_distance"
                )
            ),
            key=lambda candidate_id: (-fit_by_id[candidate_id], candidate_id),
        )
        for kind in ("visit", "dining", "transport", "lodging")
    }


def authoring_domains(
    catalog: RecommendationCatalog,
    *,
    day_count: int,
    skeleton_only: bool = False,
) -> set[str]:
    """Allow authored places where selected supply is sparse across the trip."""
    ids_by_kind = selected_ids_by_kind(catalog, skeleton_only=skeleton_only)
    domains = {
        kind
        for kind in ("visit", "dining")
        if len(ids_by_kind[kind]) < max(day_count, 1)
    }
    if not skeleton_only and not ids_by_kind["transport"]:
        domains.add("transport")
    return domains


def _placement_capabilities(
    catalog: RecommendationCatalog,
    *,
    skeleton_only: bool = False,
    selection_plan: CandidateSelectionPlan | None = None,
) -> list[dict[str, Any]]:
    """Expose only typed placement facts needed to compose a legal topology."""
    if selection_plan is not None:
        selected, _alternatives = selected_candidate_capabilities(
            catalog=catalog,
            selection_plan=selection_plan,
        )
        return [
            capability.model_dump(mode="json", exclude_none=True)
            for capability in selected
            if not (
                skeleton_only
                and capability.candidate_kind == "transport"
                and capability.schedule_capabilities.get("transport_class")
                != "long_distance"
            )
        ]
    candidate_index = catalog.candidate_index()
    fit_by_id: dict[str, Any] = {}
    for result in catalog.admission_results:
        if result.status != "passed" or result.selection_slot_id is not None:
            continue
        fit_by_id[result.candidate_id] = result.fit_scores
    capabilities: list[dict[str, Any]] = []
    for candidate_id in sorted(fit_by_id):
        candidate = candidate_index[candidate_id]
        if (
            skeleton_only
            and isinstance(candidate, TransportCandidate)
            and candidate.transport_class != "long_distance"
        ):
            continue
        scores = fit_by_id[candidate_id]
        item: dict[str, Any] = {
            "candidate_id": candidate_id,
            "candidate_kind": candidate.candidate_kind,
            "destination_id": candidate.destination_id,
            "budget_fit": round(scores.budget_fit, 2),
            "weather_fit": round(scores.weather_fit, 2),
            "constraint_fit": round(scores.constraint_fit, 2),
        }
        if isinstance(candidate, VisitCandidate):
            item.update(name=candidate.name, place_id=candidate.place_id)
        elif isinstance(candidate, DiningCandidate):
            item.update(
                name=candidate.branch_name,
                place_id=candidate.place_id,
                meal_types=candidate.meal_types,
            )
        elif isinstance(candidate, TransportCandidate):
            item.update(
                transport_class=candidate.transport_class,
                from_place_id=candidate.from_endpoint.place_id,
                to_place_id=candidate.to_endpoint.place_id,
                departure_date=(
                    candidate.departure_at.date().isoformat()
                    if candidate.departure_at is not None
                    else None
                ),
                arrival_date=(
                    candidate.arrival_at.date().isoformat()
                    if candidate.arrival_at is not None
                    else None
                ),
            )
        elif isinstance(candidate, LodgingCandidate):
            item.update(
                name=candidate.property_name,
                check_in_date=candidate.check_in_date.isoformat(),
                check_out_date=candidate.check_out_date.isoformat(),
            )
        capabilities.append(item)
    return capabilities
