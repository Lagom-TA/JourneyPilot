from __future__ import annotations

from typing import Mapping

from travel_agent.entities.candidate_intent import CandidateIntentMatch
from travel_agent.entities.candidate_selection import CandidateSelectionPlan
from travel_agent.entities.state import TravelAgentState
from travel_agent.llm.router import get_model_router
from travel_agent.llm.task_routing import TaskKind, llm_for_task
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.planning.research.requirements import _trip_duration_days
from travel_agent.services.candidate_intent_evaluation import evaluate_candidate_intents
from travel_agent.services.candidate_ranking import rank_candidates
from travel_agent.services.candidate_selection import (
    build_candidate_selection_plan,
    selection_policy_from_intent_spec,
)
from travel_agent.services.day_planning import daily_planning_windows


async def evaluate_catalog(
    state: TravelAgentState, catalog: RecommendationCatalog
) -> tuple[
    RecommendationCatalog, CandidateSelectionPlan, dict[str, CandidateIntentMatch]
]:
    matches, evaluation_cache = await evaluate_candidate_intents(
        catalog=catalog,
        intent_spec=state.intent_spec,
        llm=llm_for_task(get_model_router(), TaskKind.CANDIDATE_EVALUATION),
        cache=state.candidate_intent_evaluation_cache,
    )
    ranking_scores = rank_candidates(
        catalog=catalog,
        intent_spec=state.intent_spec,
        matches=matches,
    )
    catalog = catalog.model_copy(
        update={
            "candidate_intent_matches": matches,
            "candidate_ranking_scores": ranking_scores,
        }
    )
    destination_count = len(
        [
            destination
            for destination in (state.controlled_trip_identity or {}).get(
                "destinations", []
            )
            if isinstance(destination, Mapping)
        ]
    )
    selection_plan = build_candidate_selection_plan(
        catalog=catalog,
        intent_spec=state.intent_spec,
        ranking_scores=ranking_scores,
        duration_days=_trip_duration_days(state),
        destination_count=destination_count,
        selection_policy=selection_policy_from_intent_spec(
            state.intent_spec,
            avoid_previous_candidate_ids=state.previous_selected_candidate_ids,
        ),
    )

    windows = daily_planning_windows(state, catalog, selection_plan)
    if len(windows) == _trip_duration_days(state) and all(
        window["apply_capacity"] for window in windows
    ):
        selection_plan = build_candidate_selection_plan(
            catalog=catalog,
            intent_spec=state.intent_spec,
            ranking_scores=ranking_scores,
            duration_days=len(windows),
            destination_count=destination_count,
            selection_policy=selection_plan.selection_policy,
            daily_visit_minutes=[window["visit_minutes"] for window in windows],
            daily_destination_ids=[window["destination_id"] for window in windows],
        )

    return catalog, selection_plan, evaluation_cache
