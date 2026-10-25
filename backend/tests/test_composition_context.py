from datetime import date

from tests.agent_behavior.test_intent_research_ranking_selection import _catalog, _spec
from tests.test_run_budget_boundaries import _draft
from travel_agent.planning.itinerary.prompts import _build_composition_prompt
from travel_agent.entities.planning_generation import PlanningGeneration
from travel_agent.entities.state import TravelAgentState
from travel_agent.planning.requirements.inputs import MinimumDeliveryDraft
from travel_agent.services.candidate_selection import build_candidate_selection_plan


def state():
    spec, catalog = _spec(), _catalog()
    selection = build_candidate_selection_plan(
        catalog=catalog,
        intent_spec=spec,
        ranking_scores=[],
        duration_days=1,
        destination_count=1,
    )
    draft_data = _draft().model_dump()
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


def test_fixed_composition_contract_does_not_change_with_task_or_schema_scope():
    original = state()
    changed = original.model_copy(
        update={
            "run_id": "another",
            "composition_failure_context": "repair gap",
            "session_anchor": {
                "summary": "prior Tokyo fact",
                "key_constraints": ["不要爬楼"],
            },
        }
    )
    first = _build_composition_prompt(
        original, "Tokyo museum", required_candidate_kinds={"visit"}
    )
    second = _build_composition_prompt(
        changed, "Tokyo dining", required_candidate_kinds={"visit", "dining"}
    )
    assert first.system == second.system
    assert first.runtime != second.runtime
    assert "Tokyo dining" not in second.system
    assert second.runtime.count("不要爬楼") == 1
    assert second.runtime.count("prior Tokyo fact") == 1
    assert "<json_schema>" in second.runtime and "<json_schema>" not in second.system
    assert "dining" in second.runtime and "repair gap" in second.runtime
