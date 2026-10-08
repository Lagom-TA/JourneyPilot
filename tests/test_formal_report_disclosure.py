from datetime import date, datetime, timezone
from types import SimpleNamespace

from tests.agent_behavior.test_intent_composition_fidelity import _intent, _intent_spec, _workspace
from travel_agent.entities.candidate_intent import CandidateIntentMatch, IntentMatchStatus
from travel_agent.entities.delivery_bundle import CostCoverageSummary, ReportDestination
from travel_agent.entities.intent_coverage import IntentContractSnapshot
from travel_agent.entities.intent_spec import IntentKind, IntentStrength, ScalarIntentValue
from travel_agent.services.composition_rule_compiler import compile_composition_rules
from travel_agent.services.intent_verification import evaluate_intent_fidelity
from travel_agent.services import delivery_projection


def test_report_keeps_unverifiable_requirement_after_bounded_fidelity_release(monkeypatch):
    intent = _intent("intent_architecture", kind=IntentKind.THEME,
                     strength=IntentStrength.HARD, value=ScalarIntentValue(value="architecture")).model_copy(
                         update={"public_summary": "行程以历史建筑为主题。"})
    spec = _intent_spec(intent)
    report, gaps = evaluate_intent_fidelity(
        intent_spec=spec, rules=compile_composition_rules(spec),
        workspace=_workspace(placements=[("candidate_a", "day_1", 13)],
                             matches=[CandidateIntentMatch(
                                 candidate_id="candidate_a", intent_id=intent.intent_id,
                                 status=IntentMatchStatus.UNKNOWN, method="semantic_batch_evaluation",
                                 reason_code="insufficient_evidence")]),
        repair_budget_exhausted=True,
    )
    assert report.deviations and gaps
    assert report.items[0].status.value == "unverifiable"
    itinerary = SimpleNamespace(
        visit_stops=[], dining_stops=[], lodging_stays=[], transport_legs=[], custom_blocks=[],
        day_plans=[SimpleNamespace(day_id="day_1", day=1, date=date(2026, 10, 10),
                                  destination_id="city", theme="建筑", timeline=[])],
        duration_days=1, cost_summary=CostCoverageSummary(
            priced_component_count=0, budget_relevant_component_count=1,
            coverage="none", budget_status="unknown"), highlights=[], important_notes=[],
    )
    workspace = SimpleNamespace(
        itinerary=itinerary, workspace_revision=0, user_input_anchors=[], selection_slots=[],
        recommendation_catalog=SimpleNamespace(candidate_index=lambda: {}),
        intent_contract_snapshot=IntentContractSnapshot.from_intent_spec(spec),
        intent_coverage_report=report,
    )
    # Identity/citation projection is independent of the audited fidelity report.
    monkeypatch.setattr(delivery_projection, "project_public_citations", lambda *args: [])
    monkeypatch.setattr(delivery_projection, "_report_destinations", lambda *args: [
        ReportDestination(destination_id="city", display_name="测试城市")])
    projected = delivery_projection.project_report(
        workspace, SimpleNamespace(fact_assertions=[], fact_data_revision=0),
        SimpleNamespace(days=[], weather_data_revision=0), generated_at=datetime.now(timezone.utc),
    )
    notes = projected.document.important_notes
    assert len(notes) == 1
    assert intent.public_summary in notes[0]
    assert "intent_architecture" not in notes[0]
    assert "unverifiable" not in notes[0]
