"""计划确认、追加要求与研究运行控制。"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from travel_agent.planning.delivery.minimum_draft import (
    build_minimum_delivery_draft,
    minimum_delivery_draft_builder_node,
    seal_minimum_delivery_draft,
)
from travel_agent.planning.requirements.amendments import apply_runtime_amendments
from travel_agent.planning.requirements.approval import _build_plan_gate_payload, plan_gate_node
from travel_agent.planning.requirements.natural_language import ResearchPlan, prepare_requirements_node
from travel_agent.planning.requirements.amendment_contracts import IntentAmendment
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.cancellation import RunCancelled


def identity():
    place = {"place_id": "hangzhou", "provider": "osm", "kind": "city", "name": "杭州", "display_name": "杭州", "country_code": "CN", "latitude": 30.2, "longitude": 120.1, "admin_path": []}
    return {"origin": place, "destinations": [place], "start_date": "2026-11-05", "end_date": "2026-11-05", "party": {"adults": 2, "children": 0}, "style": {"primary": "慢游"}}


def plan():
    return ResearchPlan(summary="安排园林慢游", destination_task="研究园林", transport_task="查询交通", accommodation_task="研究住宿", itinerary_task="安排顺路行程")


async def ready_state():
    state = TravelAgentState(run_id="run", user_query="喜欢园林", controlled_trip_identity=identity())
    state = state.model_copy(update=await prepare_requirements_node(state))
    state = state.model_copy(update={"research_plan": plan()})
    return state.model_copy(update={"minimum_delivery_draft": build_minimum_delivery_draft(state)})


def gate_graph():
    builder = StateGraph(TravelAgentState)
    builder.add_node("plan_gate", plan_gate_node)
    builder.add_edge(START, "plan_gate")
    builder.add_edge("plan_gate", END)
    return builder.compile(checkpointer=InMemorySaver())


async def test_plan_confirmation_rejects_stale_version_and_seals_current_draft():
    state = await ready_state()
    graph = gate_graph()
    config = {"configurable": {"thread_id": "approval", "plan_gate_enabled": True}}
    result = await graph.ainvoke(state, config)
    gate = result["__interrupt__"][0].value
    stale = await graph.ainvoke(Command(resume={"action": "approve", "approval_token": "old"}), config)
    assert stale["__interrupt__"][0].value["approval_token"] == gate["approval_token"]
    accepted = await graph.ainvoke(Command(resume={"action": "approve", "approval_token": gate["approval_token"]}), config)
    assert accepted["minimum_delivery_draft"].planning_authorized
    assert accepted["run_budget"] is not None and accepted["run_deadline"] is not None
    assert gate["plan"]["steps"][0]["tasks"]["destination_researcher"] == "研究园林"


async def test_cancel_works_without_plan_token():
    state, graph = await ready_state(), gate_graph()
    config = {"configurable": {"thread_id": "cancel", "plan_gate_enabled": True}}
    await graph.ainvoke(state, config)
    with pytest.raises(RunCancelled):
        await graph.ainvoke(Command(resume={"action": "cancel"}), config)


@pytest.mark.parametrize("action", ["cancel", "supplement", "approve"])
async def test_gate_resume_preserves_decision_when_a_runtime_supplement_arrives(action, monkeypatch):
    from travel_agent.planning.execution import with_run_control
    from travel_agent.runtime.cancellation import run_control_registry

    async def budget_baseline():
        return None

    monkeypatch.setattr("travel_agent.planning.execution.ensure_budget_baseline", budget_baseline)
    state = await ready_state()
    builder = StateGraph(TravelAgentState)
    builder.add_node("plan_gate", with_run_control("plan_gate", plan_gate_node))
    builder.add_edge(START, "plan_gate")
    builder.add_edge("plan_gate", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": f"gate-{action}", "plan_gate_enabled": True}}
    handle = run_control_registry.register(state.run_id)
    try:
        interrupted = await graph.ainvoke(state, config)
        token = interrupted["__interrupt__"][0].value["approval_token"]
        handle.add_supplement("other", "晚上少走路", command_id="queued-supplement")
        if action == "cancel":
            with pytest.raises(RunCancelled):
                await graph.ainvoke(Command(resume={"action": "cancel"}), config)
        else:
            result = await graph.ainvoke(Command(resume={
                "action": action, "content": "改成园林" if action == "supplement" else "", "approval_token": token,
            }), config)
            if action == "supplement":
                assert result["plan_gate_amendment"].content == "改成园林"
            else:
                assert result["plan_gate_decision"]["action"] == "approve"
            assert [item.content for item in result["pending_intent_amendments"]] == ["晚上少走路"]
    finally:
        run_control_registry.clear()


async def test_gate_supplement_and_runtime_supplement_are_both_prepared(monkeypatch):
    from travel_agent.planning.execution import with_run_control
    from travel_agent.planning.requirements.approval import route_after_plan_gate
    from travel_agent.runtime.cancellation import run_control_registry

    async def budget_baseline():
        return None

    monkeypatch.setattr("travel_agent.planning.execution.ensure_budget_baseline", budget_baseline)
    state = await ready_state()
    builder = StateGraph(TravelAgentState)
    builder.add_node("plan_gate", with_run_control("plan_gate", plan_gate_node))
    builder.add_node("intent_amendment_router", lambda current: apply_runtime_amendments(current))
    builder.add_node("requirements_preparer", prepare_requirements_node)
    builder.add_edge(START, "plan_gate")
    builder.add_conditional_edges("plan_gate", route_after_plan_gate, {
        "intent_amendment_router": "intent_amendment_router",
        "requirements_preparer": "requirements_preparer",
    })
    builder.add_edge("intent_amendment_router", "requirements_preparer")
    builder.add_edge("requirements_preparer", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "combined-supplements", "plan_gate_enabled": True}}
    handle = run_control_registry.register(state.run_id)
    try:
        interrupted = await graph.ainvoke(state, config)
        token = interrupted["__interrupt__"][0].value["approval_token"]
        handle.add_supplement("other", "晚上少走路", command_id="queued-supplement")
        updated = await graph.ainvoke(Command(resume={
            "action": "supplement", "content": "改成园林", "approval_token": token,
        }), config)
    finally:
        run_control_registry.clear()
    assert "晚上少走路" in updated["current_requirements"]
    assert "改成园林" in updated["current_requirements"]
    assert updated["plan_gate_amendment"] is None
    assert updated["pending_intent_amendments"] == []


@pytest.mark.parametrize("action", ["approve", "supplement", "retry"])
async def test_rejected_queued_supplement_preserves_gate_continuation(action, monkeypatch):
    from travel_agent.planning.execution import with_run_control
    from travel_agent.planning.graph import route_after_intent_amendment
    from travel_agent.planning.requirements.approval import route_after_plan_gate
    from travel_agent.runtime.cancellation import run_control_registry

    async def budget_baseline():
        return None

    monkeypatch.setattr("travel_agent.planning.execution.ensure_budget_baseline", budget_baseline)
    state = await ready_state()
    if action == "retry":
        state = state.model_copy(update={"research_plan": None, "research_plan_error": {"code": "unavailable"}})
    builder = StateGraph(TravelAgentState)
    builder.add_node("plan_gate", with_run_control("plan_gate", plan_gate_node))
    builder.add_node("intent_amendment_router", with_run_control("intent_amendment_router", lambda current: apply_runtime_amendments(current)))
    for name in ("requirements_preparer", "research_plan_generator", "weather_context_builder"):
        builder.add_node(name, lambda _state, target=name: {"next_agent": target})
        builder.add_edge(name, END)
    builder.add_edge(START, "plan_gate")
    builder.add_conditional_edges("plan_gate", route_after_plan_gate, {
        "intent_amendment_router": "intent_amendment_router",
        "requirements_preparer": "requirements_preparer",
        "research_plan_generator": "research_plan_generator",
        "dispatcher": "weather_context_builder",
    })
    builder.add_conditional_edges("intent_amendment_router", route_after_intent_amendment, {
        "requirements_preparer": "requirements_preparer",
        "research_plan_generator": "research_plan_generator",
        "weather_context_builder": "weather_context_builder",
    })
    graph = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": f"rejected-{action}", "plan_gate_enabled": True}}
    handle = run_control_registry.register(state.run_id)
    try:
        interrupted = await graph.ainvoke(state, config)
        token = interrupted["__interrupt__"][0].value["approval_token"]
        handle.add_supplement("other", "帮我付款", command_id="rejected-supplement")
        updated = await graph.ainvoke(Command(resume={
            "action": action, "content": "改成园林" if action == "supplement" else "", "approval_token": token,
        }), config)
    finally:
        run_control_registry.clear()
    assert updated["rejected_intent_amendments"][0].reason_code == "unsupported_amendment"
    assert updated["next_agent"] == {
        "approve": "weather_context_builder", "supplement": "requirements_preparer", "retry": "research_plan_generator",
    }[action]
    if action == "supplement":
        assert updated["plan_gate_amendment"].content == "改成园林"
    if action == "approve":
        assert updated["minimum_delivery_draft"].planning_authorized


async def test_supplement_updates_one_current_text_and_changes_generation():
    state = await ready_state()
    amendment = IntentAmendment(command_id="supplement-1", category="other", content="改成园林", source_kind="run_supplement")
    state = state.model_copy(update={"pending_intent_amendments": [amendment], "intent_amendment_resume_node": "dispatcher"})
    update = apply_runtime_amendments(state)
    assert update["intent_amendment_route"] == "requirements_preparer"
    updated = state.model_copy(update=update)
    prepared = await prepare_requirements_node(updated)
    assert prepared["current_requirements"] == "喜欢园林\n后续补充：改成园林"
    assert prepared["planning_generation"].generation_id != state.planning_generation.generation_id
    assert prepared["applied_intent_amendment_ids"] == ["supplement-1"]


async def test_supplement_replaces_old_generation_results():
    from travel_agent.planning.itinerary.mutation_contracts import CompositionMutation
    from travel_agent.planning.references import EntityRef
    from travel_agent.planning.research.provider_assignments import build_provider_evidence_assignments
    from travel_agent.planning.research.provider_contracts import ProviderEvidenceOutcome
    from travel_agent.planning.research.reference_service_contracts import ProviderReferenceService
    from travel_agent.planning.weather.models import WeatherImpact

    state = await ready_state()
    mutation = CompositionMutation(
        mutation_id="old-change", generation_id=state.planning_generation.generation_id,
        mutation_type="drop", reason_code="test", created_by="user_edit",
    )
    impact = WeatherImpact(
        weather_impact_id="old-weather", date="2026-11-05",
        target_ref=EntityRef(entity_type="visit_stop", entity_id="old-stop"),
        condition_type="rain", severity="medium", action="keep",
        fact_assertion_ids=["old-fact"], data_kind="forecast", trigger_code="rain",
    )
    service = ProviderReferenceService(
        leg_role="outbound", from_name="上海", to_name="杭州", service_number="G1",
        departure_time="09:00", arrival_time="10:00", requested_date="2026-11-05",
        reference_date="2026-11-01", unconfirmed_claims=["票价"],
    )
    assignment = build_provider_evidence_assignments(
        run_id=state.run_id, worker_kind="destination_researcher",
        controlled_trip_identity=state.controlled_trip_identity, prior_scope_attempts={},
    )[0]
    outcome = ProviderEvidenceOutcome(
        scope=assignment.scope, attempt_number=0, provider_option_count=0,
        provider_option_materialized_count=0, unresolved_loss_count=0, status="no_option",
    )
    state = state.model_copy(update={
        "composition_mutations": [mutation], "weather_impacts": {impact.weather_impact_id: impact},
        "provider_reference_services": [service], "provider_evidence_outcomes": {assignment.scope.scope_id: outcome},
    })
    from travel_agent.planning.research.plan import planner_node

    builder = StateGraph(TravelAgentState)
    builder.add_node("plan_gate", plan_gate_node)
    builder.add_node("requirements_preparer", prepare_requirements_node)
    builder.add_node("planner", planner_node)
    builder.add_node("current_research_plan", lambda _state: {"research_plan": plan()})
    builder.add_edge(START, "plan_gate")
    builder.add_edge("plan_gate", "requirements_preparer")
    builder.add_edge("requirements_preparer", "current_research_plan")
    builder.add_edge("current_research_plan", "planner")
    builder.add_edge("planner", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "replace-generation-results", "plan_gate_enabled": True}}
    interrupted = await graph.ainvoke(state, config)
    token = interrupted["__interrupt__"][0].value["approval_token"]
    updated = await graph.ainvoke(Command(resume={"action": "supplement", "content": "改成园林", "approval_token": token}), config)
    assert updated["planning_generation"].generation_id != state.planning_generation.generation_id
    assert updated["composition_mutations"] == []
    assert updated["weather_impacts"] == {}
    assert updated["provider_reference_services"] == []
    assert updated["provider_evidence_outcomes"] == {}
    assert updated["agent_assignments"]["destination_researcher"]["provider_evidence_assignments"][0]["attempt_number"] == 0


async def test_a_research_worker_without_options_cannot_erase_another_workers_outcomes():
    from travel_agent.planning.research.provider_assignments import build_provider_evidence_assignments
    from travel_agent.planning.research.provider_contracts import ProviderEvidenceOutcome

    state = await ready_state()
    assignment = build_provider_evidence_assignments(
        run_id=state.run_id, worker_kind="destination_researcher",
        controlled_trip_identity=state.controlled_trip_identity, prior_scope_attempts={},
    )[0]
    outcome = ProviderEvidenceOutcome(
        scope=assignment.scope, attempt_number=0, provider_option_count=0,
        provider_option_materialized_count=0, unresolved_loss_count=0, status="no_option",
    )
    builder = StateGraph(TravelAgentState)
    builder.add_node("accommodation", lambda _state: {"provider_evidence_outcomes": {assignment.scope.scope_id: outcome}})
    builder.add_node("destination", lambda _state: {})
    builder.add_edge(START, "destination")
    builder.add_edge(START, "accommodation")
    builder.add_edge("destination", END)
    builder.add_edge("accommodation", END)
    result = await builder.compile().ainvoke(state)
    assert result["provider_evidence_outcomes"] == {assignment.scope.scope_id: outcome}


async def test_runtime_supplement_keeps_the_original_budget_and_deadline():
    from datetime import datetime, timezone

    from travel_agent.runtime.budget import ledger_for, reset_ledgers

    reset_ledgers()
    state = await ready_state()
    state = state.model_copy(update=seal_minimum_delivery_draft(state, authorized_at=datetime.now(timezone.utc)))
    ledger = ledger_for(state.run_id, state.run_budget)
    ledger.reserve_tool_call("first", "search")
    amendment = IntentAmendment(command_id="supplement-1", category="other", content="添加园林", source_kind="run_supplement")
    state = state.model_copy(update={"pending_intent_amendments": [amendment], "intent_amendment_resume_node": "dispatcher"})
    state = TravelAgentState.model_validate({**state.model_dump(), **apply_runtime_amendments(state)})
    state = TravelAgentState.model_validate({**state.model_dump(), **await prepare_requirements_node(state)})
    state = state.model_copy(update={"research_plan": plan()})
    state = TravelAgentState.model_validate({**state.model_dump(), **await minimum_delivery_draft_builder_node(state)})
    updated = seal_minimum_delivery_draft(state)
    assert updated["run_deadline"].target_at == state.run_deadline.target_at
    assert updated["run_deadline"].delivery_deadline_at == state.run_deadline.delivery_deadline_at
    assert updated["run_deadline"].draft_id == updated["minimum_delivery_draft"].draft_id
    assert updated["run_budget"] == state.run_budget
    assert ledger_for(state.run_id, updated["run_budget"]).tool_calls == 1
    TravelAgentState.model_validate({**state.model_dump(), **updated})


async def test_failed_plan_offers_retry_without_approval():
    state = (await ready_state()).model_copy(update={"research_plan": None, "research_plan_error": {"code": "unavailable"}})
    payload = _build_plan_gate_payload(state)
    assert "approve" not in payload["decision_options"]
    assert "retry" in payload["decision_options"]


async def test_retry_regenerates_the_plan_and_updates_the_gate(monkeypatch):
    from travel_agent.planning.research import research_plan_node

    state = (await ready_state()).model_copy(update={"research_plan": None, "research_plan_error": {"code": "unavailable"}})

    class Model:
        async def ainvoke(self, *_args, **_kwargs):
            return '{"summary":"重新安排","destination_task":"研究地点","transport_task":"研究交通","accommodation_task":"研究住宿","itinerary_task":"安排行程"}'

    monkeypatch.setattr(research_plan_node, "llm_for_task", lambda *_args, **_kwargs: Model())

    builder = StateGraph(TravelAgentState)
    builder.add_node("plan_gate", plan_gate_node)
    builder.add_node("research_plan_generator", research_plan_node.research_plan_generator_node)
    builder.add_edge(START, "plan_gate")
    builder.add_edge("plan_gate", "research_plan_generator")
    builder.add_edge("research_plan_generator", "plan_gate")
    graph = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "retry", "plan_gate_enabled": True}}
    failed = await graph.ainvoke(state, config)
    retried = await graph.ainvoke(
        Command(resume={"action": "retry", "approval_token": failed["__interrupt__"][0].value["approval_token"]}),
        config,
    )
    gate = retried["__interrupt__"][0].value
    assert "approve" in gate["decision_options"]
    assert "重新安排" in gate["plan_text"]
