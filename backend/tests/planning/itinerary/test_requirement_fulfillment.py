
import asyncio
from types import SimpleNamespace

from tests.fixtures.fulfillment import (
    make_composition_intent,
    make_fulfillment_spec,
    make_fulfillment_workspace,
)
from travel_agent.api.schemas.delivery import PublicBundleWorkspaceResponse
from travel_agent.planning.assignments import (
    assignment_research_round,
    resolve_agent_assignment,
)
from travel_agent.planning.delivery.intent_gate import intent_fidelity_gate_node
from travel_agent.planning.delivery.public.itinerary import _public_intent_explanations
from travel_agent.planning.delivery.requirement_contracts import EntityIntentExplanation
from travel_agent.planning.itinerary.mutation_history import (
    diff_composition_mutations,
    mark_mutations_revalidated,
)
from travel_agent.planning.requirements.candidate_match_contracts import (
    CandidateIntentMatch,
    IntentMatchStatus,
)
from travel_agent.planning.requirements.composition_compiler import (
    compile_composition_rules,
)
from travel_agent.planning.requirements.composition_contracts import (
    CompositionRule,
    CompositionRuleKind,
)
from travel_agent.planning.requirements.intent_contracts import (
    AlternativeIntentValue,
    CadenceIntentValue,
    CountIntentValue,
    IntentKind,
    IntentStrength,
    IntentTarget,
    ScalarIntentValue,
)
from travel_agent.planning.requirements.verification.coverage import (
    evaluate_intent_fidelity,
)
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.selection_contracts import (
    CandidateSelectionRole,
    SelectedCandidateCapability,
)


def _capability(
    candidate_id: str,
    *,
    rank: int,
    matched_intent_ids: list[str],
    hard_violation_intent_ids: list[str] | None = None,
) -> SelectedCandidateCapability:
    return SelectedCandidateCapability(
        candidate_id=candidate_id,
        candidate_kind="visit",
        destination_id="destination_tokyo",
        selection_role=CandidateSelectionRole.PRIMARY,
        rank=rank,
        matched_intent_ids=matched_intent_ids,
        hard_violation_intent_ids=hard_violation_intent_ids or [],
        selection_reasons=["intent fit"],
        evidence_confidence=1,
        budget_fit=1,
        weather_fit=1,
        constraint_fit=1,
        place_id=f"place_{candidate_id}",
        schedule_capabilities={"recommended_duration_minutes": 90},
    )


def _rule(
    rule_id: str,
    intent_id: str,
    kind: CompositionRuleKind,
    parameters,
    *,
    policy: str = "never_violate",
) -> CompositionRule:
    return CompositionRule(
        rule_id=rule_id,
        intent_id=intent_id,
        generation_id="generation_test",
        rule_kind=kind,
        target_domain=ResearchDomain.VISIT,
        hard=True,
        policy_on_failure=policy,
        parameters=parameters,
    )


def test_fidelity_defers_a_missing_workspace_to_delivery_quality_gate():
    update = asyncio.run(
        intent_fidelity_gate_node(
            SimpleNamespace(intent_spec=object(), trip_workspace_v2=None)
        )
    )

    assert update == {"intent_fidelity_route": "passed"}






def test_mutation_ledger_records_drop_move_and_backfill_then_revalidation():
    before = {
        "days": [
            {
                "day_id": "day_1",
                "placements": [
                    {"placement_kind": "visit", "candidate_id": "candidate_drop"},
                    {"placement_kind": "visit", "candidate_id": "candidate_move"},
                ],
            },
            {"day_id": "day_2", "placements": []},
        ]
    }
    after = {
        "days": [
            {"day_id": "day_1", "placements": []},
            {
                "day_id": "day_2",
                "placements": [
                    {"placement_kind": "visit", "candidate_id": "candidate_move"},
                    {"placement_kind": "visit", "candidate_id": "candidate_add"},
                ],
            },
        ]
    }

    mutations = diff_composition_mutations(
        before=before,
        after=after,
        generation_id="generation_test",
        reason_code="slot_aware_closeout",
        created_by="slot_backfill",
        intent_ids_by_entity={"candidate_add": ["intent_architecture"]},
        rule_ids=["rule_max"],
    )
    validated = mark_mutations_revalidated(
        mutations,
        coverage_before={"intent_architecture": "unsatisfied"},
        coverage_after={"intent_architecture": "satisfied"},
    )

    assert {item.mutation_type.value for item in validated} == {
        "drop",
        "move",
        "backfill",
    }
    assert all(item.hard_rules_revalidated for item in validated)
    added = next(item for item in validated if item.mutation_type.value == "backfill")
    assert added.affected_intent_ids == ["intent_architecture"]
    assert added.coverage_before == {"intent_architecture": "unsatisfied"}
    assert added.coverage_after == {"intent_architecture": "satisfied"}
    refreshed = mark_mutations_revalidated(
        [added],
        coverage_after={"intent_architecture": "partially_satisfied"},
    )[0]
    assert refreshed.coverage_before == {"intent_architecture": "unsatisfied"}
    assert refreshed.coverage_after == {
        "intent_architecture": "partially_satisfied"
    }


def test_assignment_resolution_uses_latest_explicit_research_round():
    key, assignment = resolve_agent_assignment(
        {
            "destination_researcher": {"objective": "initial"},
            "destination_researcher_r2": {"objective": "repair"},
            "destination_researcher_r3": {"objective": "latest"},
        },
        "destination_researcher",
    )

    assert key == "destination_researcher_r3"
    assert assignment["objective"] == "latest"
    assert assignment_research_round(key) == 2
    assert assignment_research_round("destination_researcher") == 0


def test_public_explanation_hides_internal_intent_identifier():
    payload = _public_intent_explanations(
        [
            EntityIntentExplanation(
                intent_id="intent_private",
                label="符合偏好",
                explanation="该地点与本次旅行主题一致。",
                evidence_basis="planning_judgment",
            )
        ]
    )

    assert payload == [
        {
            "label": "符合偏好",
            "explanation": "该地点与本次旅行主题一致。",
            "evidence_basis": "planning_judgment",
        }
    ]


def test_public_workspace_schema_requires_typed_fulfillment_and_generation():
    workspace = PublicBundleWorkspaceResponse.model_validate(
        {
            "contract_version": "journeypilot.trip_workspace.v10",
            "run_id": "run_test",
            "generation_id": "generation_test",
            "workspace_revision": 0,
            "itinerary": {},
            "fulfillment_summary": {
                "fulfilled": [
                    {
                        "requirement_id": "requirement_1",
                        "summary": "安排当代建筑",
                        "status": "satisfied",
                        "explanation": "已在行程中落实。",
                    }
                ],
                "deviations": [],
            },
        }
    )

    assert workspace.generation_id == "generation_test"
    assert workspace.fulfillment_summary.fulfilled[0].status == "satisfied"








def _match(candidate_id: str, intent_id: str, status: IntentMatchStatus):
    return CandidateIntentMatch(
        candidate_id=candidate_id,
        intent_id=intent_id,
        status=status,
        score=1.0,
        method="deterministic",
        supporting_fact_assertion_ids=[f"fact_{candidate_id}"],
        reason_code="test_match",
    )


def test_fidelity_detects_hard_excluded_candidate():
    intent = make_composition_intent(
        "intent_no_museum",
        kind=IntentKind.MUST_EXCLUDE,
        strength=IntentStrength.HARD,
        value=ScalarIntentValue(value="museum"),
    )
    spec = make_fulfillment_spec(intent)
    workspace = make_fulfillment_workspace(
        placements=[("candidate_museum", "day_1", 10)],
        candidate_names={"candidate_museum": "City Museum"},
        matches=[
            _match("candidate_museum", intent.intent_id, IntentMatchStatus.VIOLATED)
        ],
    )

    report, gaps = evaluate_intent_fidelity(
        intent_spec=spec,
        rules=compile_composition_rules(spec),
        workspace=workspace,
        repair_budget_exhausted=False,
    )

    assert report.items[0].status.value == "unsatisfied"
    assert report.items[0].blocking is True
    assert gaps[0].reason == "excluded_candidate_present"


def test_fidelity_routes_an_unselected_matching_candidate_to_reselection():
    intent = make_composition_intent(
        "intent_required_garden",
        kind=IntentKind.MUST_INCLUDE,
        strength=IntentStrength.HARD,
        value=ScalarIntentValue(value="garden"),
    )
    spec = make_fulfillment_spec(intent)
    workspace = make_fulfillment_workspace(
        placements=[("candidate_generic", "day_1", 10)],
        matches=[
            _match("candidate_garden", intent.intent_id, IntentMatchStatus.MATCHED)
        ],
    )

    _report, gaps = evaluate_intent_fidelity(
        intent_spec=spec,
        rules=compile_composition_rules(spec),
        workspace=workspace,
        repair_budget_exhausted=False,
    )

    assert gaps[0].retry_target == "candidate_selection"


def test_fidelity_accepts_alternatives_present_in_materialized_selection_slots():
    intent = make_composition_intent(
        "intent_alternatives",
        kind=IntentKind.ALTERNATIVES,
        strength=IntentStrength.HARD,
        value=AlternativeIntentValue(count=2),
    ).model_copy(update={"target": IntentTarget.DELIVERY})
    spec = make_fulfillment_spec(intent)
    workspace = make_fulfillment_workspace(placements=[])
    workspace.candidate_selection_plan.selection_policy.mode = "explore"
    workspace.selection_slots = [
        SimpleNamespace(
            selected_option_id="option_primary",
            options=[
                SimpleNamespace(option_id="option_primary"),
                SimpleNamespace(option_id="option_alternative"),
            ],
        )
    ]

    report, gaps = evaluate_intent_fidelity(
        intent_spec=spec,
        rules=compile_composition_rules(spec),
        workspace=workspace,
        repair_budget_exhausted=False,
    )

    assert report.items[0].status.value == "satisfied"
    assert gaps == []


def test_fidelity_checks_daily_quantity_and_cadence_window():
    quantity = make_composition_intent(
        "intent_max_two",
        kind=IntentKind.QUANTITY,
        strength=IntentStrength.HARD,
        value=CountIntentValue(operator="at_most", count=2, unit="day"),
    )
    cadence = make_composition_intent(
        "intent_daily_afternoon",
        kind=IntentKind.CADENCE,
        strength=IntentStrength.HARD,
        value=CadenceIntentValue(frequency="once_per_day", time_window="afternoon"),
    )
    spec = make_fulfillment_spec(quantity, cadence)
    workspace = make_fulfillment_workspace(
        placements=[
            ("candidate_a", "day_1", 13),
            ("candidate_b", "day_1", 14),
            ("candidate_c", "day_1", 15),
        ],
        matches=[_match("candidate_a", cadence.intent_id, IntentMatchStatus.MATCHED)],
    )

    report, gaps = evaluate_intent_fidelity(
        intent_spec=spec,
        rules=compile_composition_rules(spec),
        workspace=workspace,
        repair_budget_exhausted=False,
    )
    items = {item.intent_id: item for item in report.items}

    assert items[quantity.intent_id].missing_days == [1]
    assert items[cadence.intent_id].missing_days == [2]
    assert {gap.reason for gap in gaps} == {
        "quantity_rule_violated",
        "cadence_rule_missing",
    }


def test_fidelity_degrades_exhausted_hard_gap_and_soft_preference_to_deviations():
    hard = make_composition_intent(
        "intent_required_garden",
        kind=IntentKind.MUST_INCLUDE,
        strength=IntentStrength.HARD,
        value=ScalarIntentValue(value="garden"),
    )
    soft = make_composition_intent(
        "intent_architecture",
        kind=IntentKind.THEME,
        strength=IntentStrength.SOFT,
        value=ScalarIntentValue(value="architecture"),
    )
    spec = make_fulfillment_spec(hard, soft)

    report, gaps = evaluate_intent_fidelity(
        intent_spec=spec,
        rules=compile_composition_rules(spec),
        workspace=make_fulfillment_workspace(placements=[]),
        repair_budget_exhausted=True,
    )

    assert report.blocking_gap_ids == []
    assert len(report.deviations) == 2
    assert all(gap.blocking is False for gap in gaps)


def test_fidelity_treats_a_materialized_itinerary_as_objective_fulfillment():
    objective = make_composition_intent(
        "intent_objective",
        kind=IntentKind.OBJECTIVE,
        strength=IntentStrength.HARD,
        value=ScalarIntentValue(value="create an executable trip"),
    ).model_copy(update={"target": IntentTarget.TRIP})
    spec = make_fulfillment_spec(objective)

    report, gaps = evaluate_intent_fidelity(
        intent_spec=spec,
        rules=compile_composition_rules(spec),
        workspace=make_fulfillment_workspace(placements=[]),
        repair_budget_exhausted=False,
    )

    assert report.items[0].status.value == "satisfied"
    assert gaps == []


def test_cadence_attributes_cannot_be_satisfied_by_generic_entities():
    cadence = make_composition_intent(
        "intent_daily_cafe",
        kind=IntentKind.CADENCE,
        strength=IntentStrength.HARD,
        value=CadenceIntentValue(
            frequency="once_per_day",
            time_window="afternoon",
            required_attributes=["cafe"],
        ),
    )
    spec = make_fulfillment_spec(cadence)

    report, gaps = evaluate_intent_fidelity(
        intent_spec=spec,
        rules=compile_composition_rules(spec),
        workspace=make_fulfillment_workspace(
            placements=[
                ("candidate_generic_1", "day_1", 14),
                ("candidate_generic_2", "day_2", 15),
            ]
        ),
        repair_budget_exhausted=False,
    )

    assert report.items[0].status.value == "unsatisfied"
    assert report.items[0].missing_days == [1, 2]
    assert gaps[0].reason == "cadence_rule_missing"
