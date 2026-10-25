from __future__ import annotations

from datetime import date

from tests.fixtures.research_catalog import make_catalog, make_intent_spec
from travel_agent.planning.requirements.generation_contracts import PlanningGeneration
from travel_agent.planning.requirements.inputs import MinimumDeliveryDraft
from travel_agent.planning.research.selection_policy import build_candidate_selection_plan
from travel_agent.planning.state import TravelAgentState


def make_minimum_draft(*, authorized_at=None):
    from datetime import date

    from travel_agent.planning.requirements.inputs import (
        MinimumDeliveryDayShell,
        MinimumDeliveryDraft,
    )

    return MinimumDeliveryDraft(
        draft_id="draft_seal_budget",
        content_hash="0" * 64,
        run_id="run_seal_budget",
        planning_generation_id="generation_budget",
        controlled_trip_identity_revision=1,
        constraint_pack_revision=0,
        intent_spec_revision=1,
        intent_spec_hash="1" * 64,
        plan_revision=0,
        policy_version="minimum_delivery.v2",
        day_shells=[
            MinimumDeliveryDayShell(
                day_id="day_1",
                day=1,
                date=date(2026, 9, 1),
                destination_id="place_kyoto",
                lodging_night=False,
            )
        ],
        planning_authorized=authorized_at is not None,
        planning_authorized_at=authorized_at,
    )


def make_planning_state():
    spec, catalog = make_intent_spec(), make_catalog()
    selection = build_candidate_selection_plan(
        catalog=catalog,
        intent_spec=spec,
        ranking_scores=[],
        duration_days=1,
        destination_count=1,
    )
    draft_data = make_minimum_draft().model_dump()
    draft_data.update(
        run_id="run_test",
        planning_generation_id=spec.generation_id,
        intent_spec_hash=spec.content_hash,
    )
    draft_data["day_shells"][0].update(
        date=date(2026, 10, 10), destination_id="destination_tokyo"
    )
    return TravelAgentState(
        run_id="run_test",
        intent_spec=spec,
        intent_spec_revision=spec.revision,
        controlled_trip_identity_revision=1,
        planning_generation=PlanningGeneration(
            generation_id=spec.generation_id,
            controlled_trip_identity_revision=1,
            intent_spec_revision=spec.revision,
            constraint_pack_revision=0,
            plan_revision=0,
            identity_hash="0" * 64,
            intent_hash=spec.content_hash,
            constraint_hash="0" * 64,
        ),
        recommendation_catalog=catalog,
        candidate_selection_plan=selection,
        minimum_delivery_draft=MinimumDeliveryDraft.model_validate(draft_data),
        controlled_trip_identity={"start_date": "2026-10-10", "end_date": "2026-10-10"},
        agent_assignments={"itinerary_planner": {"objective": "Tokyo museum"}},
    )
