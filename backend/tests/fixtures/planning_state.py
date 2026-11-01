from __future__ import annotations

from datetime import date

from tests.fixtures.research_catalog import make_catalog
from travel_agent.planning.requirements.generation_contracts import PlanningGeneration
from travel_agent.planning.requirements.inputs import MinimumDeliveryDraft
from travel_agent.planning.state import TravelAgentState


def make_minimum_draft(*, authorized_at=None):
    from travel_agent.planning.requirements.inputs import (
        MinimumDeliveryDayShell,
    )

    return MinimumDeliveryDraft(
        draft_id="draft_seal_budget",
        content_hash="0" * 64,
        run_id="run_test",
        planning_generation_id="generation_test",
        day_shells=[
            MinimumDeliveryDayShell(
                day_id="day_1",
                day=1,
                date=date(2026, 10, 10),
                destination_id="destination_tokyo",
                lodging_night=False,
            )
        ],
        planning_authorized=authorized_at is not None,
        planning_authorized_at=authorized_at,
    )


def make_planning_state():
    catalog = make_catalog()
    return TravelAgentState(
        run_id="run_test",
        user_query="东京行程需求",
        current_requirements="东京行程需求",
        controlled_trip_identity={"start_date": "2026-10-10", "end_date": "2026-10-10"},
        planning_generation=PlanningGeneration(generation_id="generation_test", revision=1),
        recommendation_catalog=catalog,
        minimum_delivery_draft=make_minimum_draft(),
        agent_assignments={"itinerary_planner": {"objective": "Tokyo museum"}},
    )
