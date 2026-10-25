
import travel_agent.planning.delivery.intent_gate as planning_delivery_intent_gate
import json

import pytest
from tests.agent_behavior.test_intent_research_ranking_selection import (
    _catalog,
    _intent,
    _packet,
    _spec,
)
from tests.agent_behavior.test_itinerary_revision import checkpoint, draft, visit_entry
from tests.test_composition_context import state


from travel_agent.planning.research.discovery_contracts import CandidateDiscoveryOrigin
from travel_agent.planning.requirements.candidate_match_contracts import CandidateIntentMatch, IntentMatchStatus
from travel_agent.planning.requirements.snapshot_contracts import IntentContractSnapshot
from travel_agent.planning.requirements.intent_contracts import IntentKind, IntentStrength, IntentTarget, VerificationMode
from travel_agent.planning.itinerary.draft import ItineraryCompositionDraft
from travel_agent.planning.itinerary.materialize import materialize_trip_workspace
from travel_agent.planning.outcomes import DeliveryContractViolation
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.planning.workspace import TripWorkspaceV2
from travel_agent.planning.requirements.candidate_evaluation import evaluate_candidate_intents
from travel_agent.planning.research.selection_policy import build_candidate_selection_plan
from travel_agent.planning.requirements.composition_compiler import compile_composition_rules
from travel_agent.planning.requirements.entity_checks import check_final_entities, requirement_check_objects
from travel_agent.planning.requirements.verification.coverage import evaluate_intent_fidelity
from travel_agent.planning.requirements.verification.workspace import revalidate_workspace_intent
from travel_agent.planning.itinerary.revision import (
    MAXIMUM_COMPOSITION_REPAIR_ATTEMPTS,
)


def make_workspace(name="City Museum", *, candidate_backed=False, category="museum", target=IntentTarget.VISIT):
    intent = _intent("intent_ban", category, kind=IntentKind.MUST_EXCLUDE,
                     strength=IntentStrength.HARD, verification=VerificationMode.DETERMINISTIC)
    intent = intent.model_copy(update={"impact_stages": ["ranking", "composition"], "target": target})
    spec = _spec(intent)
    packet = _packet("candidate_visit", name, origin=CandidateDiscoveryOrigin.INTENT_QUERY,
                     query_id="query_ban", intent_id="intent_ban")
    catalog = _catalog(packet)
    plan = build_candidate_selection_plan(catalog=catalog, intent_spec=spec, ranking_scores=[],
                                          duration_days=1, destination_count=1)
    entry = visit_entry()
    if not candidate_backed:
        entry.pop("candidate_id")
        entry["authored_place"] = {
            "name": name, "local_name": name, "city": "Tokyo", "address": "1 Example Street",
            "resolved_place_id": "place_candidate_visit", "resolved_address": "1 Example Street",
            "resolved_latitude": 35.6, "resolved_longitude": 139.7,
            "selection_reason": "不去博物馆，不含海鲜", "visit_type": "other", "highlights": ["散步"],
        }
    composition = ItineraryCompositionDraft.model_validate(draft([entry]))
    workspace = materialize_trip_workspace(
        run_id="run_test", workspace_revision=0, composition=composition, catalog=catalog,
        intent_contract_snapshot=IntentContractSnapshot.from_intent_spec(spec),
        candidate_selection_plan=plan, composition_mutations=[],
    )
    return spec, workspace


def normal_state(spec, workspace, *, attempts=0):
    original = state()
    return checkpoint(
        original, intent_spec=spec,
        planning_generation=original.planning_generation.model_copy(update={"intent_hash": spec.content_hash}),
        minimum_delivery_draft=original.minimum_delivery_draft.model_copy(update={"intent_spec_hash": spec.content_hash}),
        recommendation_catalog=workspace.recommendation_catalog,
        candidate_selection_plan=workspace.candidate_selection_plan,
        trip_workspace_v2=workspace, composition_repair_attempts=attempts,
    )


def coverage(spec, workspace):
    return evaluate_intent_fidelity(intent_spec=spec, rules=compile_composition_rules(spec),
                                   workspace=workspace, repair_budget_exhausted=False)


async def test_authored_museum_uses_existing_repair_before_terminal_rejection():
    spec, workspace = make_workspace()
    current = normal_state(spec, workspace)
    repaired = checkpoint(current, **await planning_delivery_intent_gate.intent_fidelity_gate_node(current))
    assert repaired.intent_fidelity_route == "composition_repair"
    assert repaired.composition_repair_attempts == 1
    assert repaired.intent_coverage_report.items[0].status.value == "unsatisfied"
    assert repaired.trip_workspace_v2.entity_intent_checks[0].evidence_basis == "planning_judgment"
    assert repaired.trip_workspace_v2.itinerary.visit_stops[0].lineage.candidate_id is None
    exhausted = normal_state(spec, workspace, attempts=MAXIMUM_COMPOSITION_REPAIR_ATTEMPTS)
    with pytest.raises(DeliveryContractViolation, match="never-violate"):
        await planning_delivery_intent_gate.intent_fidelity_gate_node(exhausted)
    with pytest.raises(ValueError, match="never-violate"):
        revalidate_workspace_intent(workspace)


async def test_located_authored_park_is_not_rejected_for_missing_candidate_identity():
    spec, workspace = make_workspace("City Park")
    result = checkpoint(normal_state(spec, workspace),
                        **await planning_delivery_intent_gate.intent_fidelity_gate_node(normal_state(spec, workspace)))
    assert result.intent_fidelity_route == "passed"
    assert result.intent_coverage_report.items[0].status.value == "satisfied"
    lineage = result.trip_workspace_v2.itinerary.visit_stops[0].lineage
    assert lineage.lineage_kind == "authored_entity" and lineage.candidate_id is None
    assert result.trip_workspace_v2.entity_intent_checks[0].evidence_basis == "planning_judgment"


async def test_negative_description_is_not_a_positive_category_fact():
    spec, workspace = make_workspace("Riverside", category="seafood")
    assert "不含海鲜" in workspace.itinerary.visit_stops[0].selection_reason
    obj = requirement_check_objects(workspace)[0]
    assert "selection_reason" not in obj.attributes
    report, gaps = coverage(spec, workspace)
    assert report.items[0].status.value == "unverifiable"
    assert "已落实" not in report.items[0].public_explanation
    assert gaps[0].reason == "intent_evidence_unavailable"
    _, synchronous_report, _ = revalidate_workspace_intent(workspace)
    assert synchronous_report.items[0].status.value == "unverifiable"
    catalog = workspace.recommendation_catalog
    packet = catalog.research_packets[0].model_dump()
    packet["candidates"][0]["name"] = "Riverside 不含海鲜"
    catalog = _catalog(ResearchPacket.model_validate(packet))
    matches, _ = await evaluate_candidate_intents(catalog=catalog, intent_spec=spec, llm=None)
    assert matches[0].status is IntentMatchStatus.UNKNOWN


async def test_unresolved_entity_is_unverified_not_a_confirmed_violation(monkeypatch):
    spec, workspace = make_workspace("Riverside")
    calls = []

    class Model:
        async def ainvoke(self, messages, **kwargs):
            calls.append(messages)
            rows = json.loads(messages[-1]["content"])
            return json.dumps({"checks": [{"entity_id": row["entity"]["entity_id"],
                                           "intent_id": row["intent"]["intent_id"],
                                           "status": "unknown", "reason": "无类别依据"} for row in rows]})

    monkeypatch.setattr('travel_agent.planning.delivery.intent_gate.get_model_router', lambda: None)
    monkeypatch.setattr('travel_agent.planning.delivery.intent_gate.llm_for_task', lambda *args: Model())
    current = normal_state(spec, workspace, attempts=MAXIMUM_COMPOSITION_REPAIR_ATTEMPTS)
    result = checkpoint(current, **await planning_delivery_intent_gate.intent_fidelity_gate_node(current))
    assert len(calls) == 1
    item = result.intent_coverage_report.items[0]
    assert item.status.value == "unverifiable"
    assert not item.violated_entity_refs and "已落实" not in item.public_explanation
    assert result.trip_workspace_v2.entity_intent_checks[0].evidence_basis == "unverified"


async def test_same_place_facts_are_reused_without_forging_authored_lineage():
    spec, candidate_workspace = make_workspace("City Museum", candidate_backed=True)
    matches, _ = await evaluate_candidate_intents(
        catalog=candidate_workspace.recommendation_catalog, intent_spec=spec, llm=None)
    assert matches[0].status is IntentMatchStatus.VIOLATED
    _, authored_workspace = make_workspace("Riverside")
    workspaces = []
    for workspace in (candidate_workspace, authored_workspace):
        payload = workspace.model_dump()
        payload["recommendation_catalog"] = candidate_workspace.recommendation_catalog.model_copy(
            update={"candidate_intent_matches": matches})
        workspaces.append(TripWorkspaceV2.model_validate(payload))
    for workspace in workspaces:
        report, _ = coverage(spec, workspace)
        assert report.items[0].status.value == "unsatisfied"
        assert check_final_entities(workspace, spec)[0].status is IntentMatchStatus.VIOLATED
    lineage = workspaces[1].itinerary.visit_stops[0].lineage
    assert lineage.lineage_kind == "authored_entity" and lineage.candidate_id is None
    assert not lineage.fact_assertion_ids and not lineage.source_record_ids


@pytest.mark.parametrize("candidate_backed", [True, False])
@pytest.mark.parametrize("old_category, old_status, new_category, expected", [
    ("museum", IntentMatchStatus.VIOLATED, "park", "satisfied"),
    ("park", IntentMatchStatus.NOT_MATCHED, "museum", "unsatisfied"),
])
def test_changed_prohibition_rechecks_current_facts(
    candidate_backed, old_category, old_status, new_category, expected,
):
    _, original = make_workspace("City Museum", candidate_backed=candidate_backed, category=old_category)
    current_spec, _ = make_workspace("City Museum", category=new_category)
    previous_match = CandidateIntentMatch(
        candidate_id="candidate_visit", intent_id="intent_ban", status=old_status,
        method="semantic_batch_evaluation", supporting_fact_assertion_ids=["fact_candidate_visit"],
        supporting_source_record_ids=["source_candidate_visit"],
        reason_code="previous_requirement", public_reason=f"旧要求：{old_category}",
    )
    payload = original.model_dump()
    payload["intent_contract_snapshot"] = IntentContractSnapshot.from_intent_spec(current_spec)
    payload["recommendation_catalog"] = original.recommendation_catalog.model_copy(
        update={"candidate_intent_matches": [previous_match]},
    )
    changed = TripWorkspaceV2.model_validate(payload)

    report, _ = coverage(current_spec, changed)

    assert report.items[0].status.value == expected
    if not candidate_backed:
        assert changed.itinerary.visit_stops[0].lineage.candidate_id is None


async def test_semantic_result_survives_checkpoint_but_not_an_entity_edit(monkeypatch):
    spec, workspace = make_workspace("Riverside")
    calls = []

    class Model:
        async def ainvoke(self, messages, **kwargs):
            calls.append(messages)
            row = json.loads(messages[-1]["content"])[0]
            return json.dumps({"checks": [{"entity_id": row["entity"]["entity_id"],
                                           "intent_id": row["intent"]["intent_id"],
                                           "status": "not_matched", "reason": "名称与属性表示室外园林"}]})

    monkeypatch.setattr('travel_agent.planning.delivery.intent_gate.get_model_router', lambda: None)
    monkeypatch.setattr('travel_agent.planning.delivery.intent_gate.llm_for_task', lambda *args: Model())
    current = normal_state(spec, workspace)
    result = checkpoint(current, **await planning_delivery_intent_gate.intent_fidelity_gate_node(current))
    assert len(calls) == 1
    saved_workspace = TripWorkspaceV2.model_validate(result.trip_workspace_v2.model_dump(mode="json"))
    _, report, _ = revalidate_workspace_intent(saved_workspace)
    assert report.items[0].status.value == "satisfied"
    payload = saved_workspace.model_dump()
    payload["itinerary"]["visit_stops"][0]["name"] = "Unclassified New Place"
    edited = TripWorkspaceV2.model_validate(payload)
    _, report, _ = revalidate_workspace_intent(edited)
    assert report.items[0].status.value == "unverifiable"
    assert len(calls) == 1
