"""Untrusted model assertions must not authorize research without user confirmation."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from travel_agent.planning.graph import build_travel_workflow
from travel_agent.planning.nodes import NODE_DISPATCHER
from travel_agent.planning.requirements.constraints import loading
from travel_agent.planning.requirements.normalization import node as normalization
from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.weather.context_builder import WeatherContextBuilder
from travel_agent.storage import cost_ledger_store


def _place(name):
    return {
        "place_id": f"offline:{name}", "provider": "osm", "kind": "city", "name": name,
        "display_name": name, "country_code": "CN", "latitude": 30.2,
        "longitude": 120.1, "admin_path": [],
    }


IDENTITY = {
    "origin": _place("上海"), "destinations": [_place("杭州")],
    "start_date": "2026-11-05", "end_date": "2026-11-07",
    "party": {"adults": 2, "children": 0},
    "style": {"primary": "经典均衡", "secondary_interests": []},
}


class Memory:
    async def get_user_profile(self, *_args, **_kwargs):
        return None

    async def list_manual_facts(self, *_args, **_kwargs):
        return []

    async def search_facts(self, *_args, **_kwargs):
        return []


class Ledger:
    async def run_summary(self, _run_id):
        return {}


class Weather:
    name = "offline"

    def __init__(self):
        self.calls = []

    async def fetch_weather(self, request):
        self.calls.append(request)
        raise AssertionError("weather must not run before a valid, confirmed plan")


class MaliciousModel:
    capabilities = SimpleNamespace(supports_json_schema=False)

    def __init__(self, mode):
        self.mode = mode

    async def ainvoke(self, messages, **_kwargs):
        payload = json.loads(messages[-1]["content"])
        rows = []
        forbidden = "咖啡" if self.mode == "negative" else "东京迪士尼"
        for clause in payload["clauses"]:
            text = clause["text"]
            if self.mode == "negative" and "不喝咖啡" not in text:
                intent = {
                    "kind": "objective", "target": "trip", "strength": "hard", "priority": 90,
                    "value": {"value_type": "scalar", "value": text},
                    "verification_mode": "mixed", "impact_stages": ["research", "composition"],
                    "public_summary": text,
                }
                constraints = []
            else:
                intent = {
                    "kind": "must_include", "target": "dining", "strength": "hard", "priority": 90,
                    "value": {"value_type": "category", "categories": [forbidden]},
                    "verification_mode": "mixed", "impact_stages": ["research", "composition"],
                    "public_summary": f"优先研究{forbidden}",
                }
                constraints = ([{"category": "dietary_restriction", "value": "不喝咖啡", "params": {}}]
                               if self.mode == "negative" else [])
            rows.append({
                "clause_id": clause["clause_id"], "disposition": "mapped_to_intent",
                "reason_code": None, "intents": [intent], "constraints": constraints,
            })
        plan = None if self.mode == "fallback" else {
            "domains": [
                {"domain": "visit", "focus_atoms": ["景点"], "search_terms": ["景点"]},
                {"domain": "dining", "focus_atoms": [forbidden], "search_terms": [forbidden]},
                {"domain": "lodging", "focus_atoms": ["住宿"], "search_terms": ["住宿"]},
                {"domain": "long_distance_transport", "focus_atoms": ["交通"], "search_terms": ["交通"]},
            ]
        }
        return json.dumps({"clauses": rows, "research_plan": plan}, ensure_ascii=False)


def _offline(monkeypatch, model):
    for module in (normalization, loading):
        monkeypatch.setattr(module, "get_model_router", lambda: object())
        monkeypatch.setattr(module, "llm_for_task", lambda *_args, **_kwargs: model)
    monkeypatch.setattr(loading, "UserProfileMemory", Memory)
    monkeypatch.setattr(loading, "MemoryStore", Memory)
    monkeypatch.setattr(cost_ledger_store, "get_cost_ledger_store", lambda: Ledger())


async def test_model_is_not_asked_to_write_a_plan_before_missing_requirements_are_resolved(monkeypatch):
    class Model:
        capabilities = SimpleNamespace(supports_json_schema=False)
        prompts = []

        async def ainvoke(self, messages, **kwargs):
            self.prompts.append((messages, kwargs))
            payload = json.loads(messages[-1]["content"])
            return json.dumps({
                "clauses": [{
                    "clause_id": row["clause_id"], "disposition": "unresolved",
                    "reason_code": "needs_clarification", "intents": [], "constraints": [],
                } for row in payload["clauses"]],
                # A malicious provider may still add an unsolicited plan.
                "research_plan": {"domains": [{"domain": "visit", "focus_atoms": ["景点"], "search_terms": ["景点"]}]},
            }, ensure_ascii=False)

    model = Model()
    _offline(monkeypatch, model)
    graph = build_travel_workflow().compile(checkpointer=InMemorySaver(), interrupt_before=[NODE_DISPATCHER])
    config = {"configurable": {"thread_id": "missing-before-plan", "plan_gate_enabled": True}}
    result = await graph.ainvoke(TravelAgentState(
        run_id="missing-before-plan", user_id="local", user_query="长辈行动限制待明确",
        controlled_trip_identity=IDENTITY,
    ), config)
    assert result["__interrupt__"][0].value["plan"]["steps"] == []
    assert len(model.prompts) == 1
    messages, kwargs = model.prompts[0]
    assert "顶层还要输出 research_plan" not in messages[0]["content"]
    schema = kwargs["response_format"]["json_schema"]["schema"]
    assert "research_plan" not in schema.get("properties", {})
    candidate = result.get("request_contract_candidate") or result.get("request_contract")
    assert candidate is None or not getattr(candidate, "research_plan", None)


@pytest.mark.parametrize("mode", ["invented", "negative", "fallback"])
async def test_unverified_model_values_cannot_produce_an_approvable_plan(monkeypatch, mode):
    _offline(monkeypatch, MaliciousModel(mode))
    weather = Weather()
    graph = build_travel_workflow().compile(checkpointer=InMemorySaver(), interrupt_before=[NODE_DISPATCHER])
    config = {"configurable": {
        "thread_id": f"semantic-{mode}", "plan_gate_enabled": True,
        "weather_context_builder": WeatherContextBuilder([weather], max_retries_per_provider=0),
    }}
    user_query = "规划杭州旅行，不喝咖啡" if mode == "negative" else "规划杭州旅行"
    before = await graph.ainvoke(TravelAgentState(
        run_id=f"semantic-{mode}", user_id="local", user_query=user_query,
        controlled_trip_identity=IDENTITY,
    ), config)
    payload = before["__interrupt__"][0].value
    assert payload["plan"]["steps"] == [], "unverified semantics must be clarified, not presented as a plan"
    assert "phase" not in payload
    assert payload["plan_text"].startswith("**需要先补充的信息**")
    assert "approve" not in payload["decision_options"]
    assert not before.get("research_query_plan")
    assert weather.calls == []
    replay = await graph.ainvoke(Command(resume={"action": "approve", "approval_token": payload["approval_token"]}), config)
    assert replay["__interrupt__"]
    assert weather.calls == []


class AuthorizedPlanningModel:
    capabilities = SimpleNamespace(supports_json_schema=False)

    def __init__(self, variant="first", *, fail_first_selection=False):
        self.variant = variant
        self.fail_first_selection = fail_first_selection
        self.normalization_calls = 0
        self.selection_calls = 0
        self.selected_search_labels = []

    async def ainvoke(self, messages, **_kwargs):
        payload = json.loads(messages[-1]["content"])
        if "clauses" in payload:
            self.normalization_calls += 1
            rows = []
            for clause in payload["clauses"]:
                text = clause["text"]
                rows.append({
                    "clause_id": clause["clause_id"],
                    "disposition": "mapped_to_intent",
                    "reason_code": None,
                    "intents": [{
                        "kind": "objective", "target": "trip", "strength": "hard",
                        "priority": 90,
                        "value": {"value_type": "scalar", "value": text},
                        "verification_mode": "mixed",
                        "impact_stages": ["research", "composition"],
                        "public_summary": text,
                    }],
                    "constraints": [],
                })
            return json.dumps({"clauses": rows}, ensure_ascii=False)

        self.selection_calls += 1
        if self.fail_first_selection and self.selection_calls == 1:
            raise RuntimeError("offline selection failure")
        self.selected_search_labels = []
        domains = {}
        for domain in payload["required_domains"]:
            candidates = [item for item in payload["candidates"] if item["domain"] == domain]
            selected = candidates[0] if self.variant == "first" else candidates[-1]
            self.selected_search_labels.append(selected["label"])
            domains[domain] = {
                "focus_candidate_ids": [selected["candidate_id"]],
                "search_candidate_ids": [selected["candidate_id"]],
            }
        return json.dumps({"domains": domains})


def _install_planning_model(monkeypatch, model):
    from travel_agent.planning.research import research_plan_node

    _offline(monkeypatch, model)
    monkeypatch.setattr(research_plan_node, "get_model_router", lambda: object())
    monkeypatch.setattr(research_plan_node, "llm_for_task", lambda *_args, **_kwargs: model)


class ApplicableWeather(Weather):
    async def fetch_weather(self, request):
        from travel_agent.integrations.weather import WeatherProviderNotApplicable

        self.calls.append(request)
        raise WeatherProviderNotApplicable("offline fixture")


async def test_confirmed_model_selection_drives_the_approved_queries(monkeypatch):
    observed = {}
    for variant in ("first", "second"):
        model = AuthorizedPlanningModel(variant)
        _install_planning_model(monkeypatch, model)
        weather = ApplicableWeather()
        graph = build_travel_workflow().compile(
            checkpointer=InMemorySaver(), interrupt_before=[NODE_DISPATCHER],
        )
        run_id = f"authorized-selection-{variant}"
        config = {"configurable": {
            "thread_id": run_id, "plan_gate_enabled": True,
            "weather_context_builder": WeatherContextBuilder([weather], max_retries_per_provider=0),
        }}
        confirmed = await graph.ainvoke(TravelAgentState(
            run_id=run_id, user_id="local", user_query="规划杭州旅行",
            controlled_trip_identity=IDENTITY,
        ), config)
        gate = confirmed["__interrupt__"][0].value
        assert "phase" not in gate
        assert confirmed["semantic_receipt"] is None
        assert gate["plan"]["source"] == "model"
        assert "approve" in gate["decision_options"]
        assert confirmed["request_contract"].research_plan is not None
        assert weather.calls == []
        assert model.normalization_calls == 1
        assert model.selection_calls == 1
        before_queries = confirmed["research_query_plan"].content_hash
        before_assignments = confirmed["agent_assignments"]

        approved = await graph.ainvoke(Command(resume={
            "action": "approve", "approval_token": gate["approval_token"],
        }), config)
        assert approved["research_query_plan"].content_hash == before_queries
        assert approved["agent_assignments"] == before_assignments
        assert approved["minimum_delivery_draft"].planning_authorized
        assert len(weather.calls) == 1
        assert model.normalization_calls == 1
        assert model.selection_calls == 1

        from travel_agent.planning.research.dispatch import dispatcher_node

        dispatched = await dispatcher_node(TravelAgentState.model_validate({
            key: value for key, value in approved.items() if key != "__interrupt__"
        }))
        assert dispatched["next_agent"] == "dispatch_group"
        query_text = " ".join(
            [query.query_text for query in approved["research_query_plan"].queries]
            + [alias for query in approved["research_query_plan"].queries for alias in query.aliases]
        )
        for label in model.selected_search_labels:
            assert label in query_text
        observed[variant] = (gate["plan"]["research_scope"], query_text)

    assert observed["first"][0] != observed["second"][0]
    assert observed["first"][1] != observed["second"][1]


async def test_plan_model_failure_requires_explicit_retry_without_renormalizing(monkeypatch):
    model = AuthorizedPlanningModel(fail_first_selection=True)
    _install_planning_model(monkeypatch, model)
    weather = ApplicableWeather()
    graph = build_travel_workflow().compile(
        checkpointer=InMemorySaver(), interrupt_before=[NODE_DISPATCHER],
    )
    config = {"configurable": {
        "thread_id": "authorized-selection-retry", "plan_gate_enabled": True,
        "weather_context_builder": WeatherContextBuilder([weather], max_retries_per_provider=0),
    }}
    failed = await graph.ainvoke(TravelAgentState(
        run_id="authorized-selection-retry", user_id="local", user_query="规划杭州旅行",
        controlled_trip_identity=IDENTITY,
    ), config)
    failure_gate = failed["__interrupt__"][0].value
    assert "approve" not in failure_gate["decision_options"]
    assert "retry" in failure_gate["decision_options"]
    assert failed["request_contract"].research_plan is None
    assert weather.calls == []

    replay = await graph.ainvoke(Command(resume={
        "action": "approve", "approval_token": failure_gate["approval_token"],
    }), config)
    assert "retry" in replay["__interrupt__"][0].value["decision_options"]
    assert model.selection_calls == 1
    assert weather.calls == []

    recovered = await graph.ainvoke(Command(resume={
        "action": "retry", "approval_token": failure_gate["approval_token"],
    }), config)
    assert recovered["__interrupt__"][0].value["plan"]["source"] == "model"
    assert model.normalization_calls == 1
    assert model.selection_calls == 2
    assert weather.calls == []


class FiveDomainPlanningModel(AuthorizedPlanningModel):
    async def ainvoke(self, messages, **kwargs):
        payload = json.loads(messages[-1]["content"])
        if "clauses" not in payload:
            self.candidate_count = len(payload["candidates"])
            self.candidate_labels = [item["label"] for item in payload["candidates"]]
        if "clauses" in payload:
            self.normalization_calls += 1
            rows = []
            for clause in payload["clauses"]:
                text = clause["text"]
                if "小吃" in text:
                    kind, target, value = "must_include", "dining", {"value_type": "category", "categories": ["小吃"]}
                    stages = ["research", "composition"]
                elif "地铁" in text:
                    kind, target, value = "must_include", "local_transport", {"value_type": "category", "categories": ["地铁"]}
                    stages = ["research", "composition"]
                elif "报告" in text:
                    kind, target = "output_requirement", "delivery"
                    value = {"value_type": "output_requirement", "required_field": text, "applies_to": "delivery"}
                    stages = ["projection"]
                else:
                    kind, target, value = "objective", "trip", {"value_type": "scalar", "value": text}
                    stages = ["research", "composition"]
                rows.append({
                    "clause_id": clause["clause_id"], "disposition": "mapped_to_intent",
                    "reason_code": None,
                    "intents": [{
                        "kind": kind, "target": target, "strength": "hard", "priority": 90,
                        "value": value, "verification_mode": "mixed", "impact_stages": stages,
                        "public_summary": text,
                    }],
                    "constraints": [],
                })
            return json.dumps({"clauses": rows}, ensure_ascii=False)
        return await super().ainvoke(messages, **kwargs)


async def test_five_domain_candidate_budget_is_bounded_but_uncompiled_domain_blocks_approval(monkeypatch):
    model = FiveDomainPlanningModel()
    _install_planning_model(monkeypatch, model)
    graph = build_travel_workflow().compile(
        checkpointer=InMemorySaver(), interrupt_before=[NODE_DISPATCHER],
    )
    config = {"configurable": {"thread_id": "five-domain-plan", "plan_gate_enabled": True}}
    confirmed = await graph.ainvoke(TravelAgentState(
        run_id="five-domain-plan", user_id="local",
        user_query="规划杭州旅行，想吃小吃，市内坐地铁，报告要简洁",
        controlled_trip_identity=IDENTITY,
    ), config)
    gate = confirmed["__interrupt__"][0].value
    assert "phase" not in gate
    assert gate["plan"]["source"] == "unrecorded"
    assert "approve" not in gate["decision_options"]
    assert "retry" in gate["decision_options"]
    assert model.candidate_count == 40
    assert "output_requirement" not in model.candidate_labels
    assert "报告要简洁" in confirmed["research_brief"].delivery_requirements
    assert len(confirmed["request_contract"].research_plan.domains) == 5


@pytest.mark.parametrize("form", ["scalar", "scalar_phrase", "category_phrase"])
def test_scalar_exclusion_removes_the_object_from_safe_research_candidates(form):
    from travel_agent.planning.requirements.identity_contracts import ControlledTripIdentity
    from travel_agent.planning.requirements.intent_contracts import (
        CategoryIntentValue, IntentItem, IntentKind, IntentStrength, IntentTarget,
        ScalarIntentValue, VerificationMode,
    )
    from travel_agent.planning.research.domains import ResearchDomain
    from travel_agent.planning.research.research_plan_validation import (
        build_research_plan_binding, grounded_research_atoms,
    )

    identity = ControlledTripIdentity.model_validate(IDENTITY)
    value = (
        ScalarIntentValue(value="博物馆")
        if form == "scalar"
        else ScalarIntentValue(value="不去博物馆")
        if form == "scalar_phrase"
        else CategoryIntentValue(categories=["不去博物馆"])
    )
    exclusion = IntentItem(
        intent_id="intent_no_museum", kind=IntentKind.MUST_EXCLUDE,
        target=IntentTarget.VISIT, strength=IntentStrength.HARD, priority=90,
        value=value, source_kind="current_request",
        source_ref_id="query_main", source_text="不要去博物馆",
        verification_mode=VerificationMode.MIXED, impact_stages=["research"],
        public_summary="不要去博物馆",
    )
    binding = build_research_plan_binding(
        identity=identity, active_items=[exclusion], constraint_pack={"constraints": []},
        clause_texts=["不要去博物馆"],
    )
    assert binding.contradicts_restriction("博物馆") == "博物馆"
    assert "博物馆" not in grounded_research_atoms(
        identity=identity, active_items=[exclusion], constraint_pack={"constraints": []},
        clause_texts=["不要去博物馆"], domain=ResearchDomain.VISIT,
    )


async def test_internal_profile_text_never_enters_questions_or_research(monkeypatch):
    from travel_agent.planning.requirements.constraints.loading import LoadedConstraintSources

    model = AuthorizedPlanningModel()
    _install_planning_model(monkeypatch, model)
    profile = SimpleNamespace(
        auto_portrait="内部画像秘密",
        preferences=SimpleNamespace(
            travel_styles=[], dietary_restrictions=[], typical_budget_level="",
            accommodation_type="", pace="", preferred_transport=[],
        ),
    )

    async def load_profile(_state):
        return LoadedConstraintSources(
            user_profile=profile, manual_memory_facts=[], manual_memory_truncated=False,
            memory_facts=[], missing_layers=[], partial_reasons=[],
        )

    monkeypatch.setattr(normalization, "load_constraint_sources", load_profile)
    graph = build_travel_workflow().compile(
        checkpointer=InMemorySaver(), interrupt_before=[NODE_DISPATCHER],
    )
    config = {"configurable": {"thread_id": "internal-profile", "plan_gate_enabled": True}}
    result = await graph.ainvoke(TravelAgentState(
        run_id="internal-profile", user_id="local", user_query="规划杭州旅行",
        controlled_trip_identity=IDENTITY,
    ), config)
    gate = result["__interrupt__"][0].value
    assert gate["plan"]["source"] == "model"
    visible = gate["plan_text"] + " " + " ".join(
        query.query_text for query in result["research_query_plan"].queries
    )
    assert "内部画像秘密" not in visible


def test_model_summary_and_constraint_params_cannot_create_research_atoms():
    from travel_agent.planning.requirements.identity_contracts import ControlledTripIdentity
    from travel_agent.planning.requirements.intent_contracts import (
        IntentItem, IntentKind, IntentStrength, IntentTarget, ScalarIntentValue, VerificationMode,
    )
    from travel_agent.planning.research.domains import ResearchDomain
    from travel_agent.planning.research.research_plan_validation import (
        build_research_plan_binding, grounded_research_atoms,
    )

    identity = ControlledTripIdentity.model_validate(IDENTITY)
    intent = IntentItem(
        intent_id="intent_history", kind=IntentKind.THEME, target=IntentTarget.VISIT,
        strength=IntentStrength.SOFT, priority=50,
        value=ScalarIntentValue(value="历史"), source_kind="current_request",
        source_ref_id="query_main", source_text="喜欢历史",
        verification_mode=VerificationMode.MIXED, impact_stages=["research"],
        public_summary="安排东京迪士尼",
    )
    pack = {"constraints": [{
        "constraint_id": "constraint_hotel", "category": "accommodation_preference",
        "value": "安静住宿", "public_summary": "安静住宿", "type": "soft", "status": "active",
        "params": {"prefer": ["东京迪士尼"]},
        "source_refs": [{"source": "current_query", "origin_ref": "query_main"}],
    }]}
    binding = build_research_plan_binding(
        identity=identity, active_items=[intent], constraint_pack=pack,
        clause_texts=["喜欢历史"],
    )
    assert "历史" in binding.focus_atoms
    assert "东京迪士尼" not in binding.focus_atoms
    assert "东京迪士尼" not in binding.search_atoms
    assert "东京迪士尼" not in grounded_research_atoms(
        identity=identity, active_items=[intent], constraint_pack=pack,
        clause_texts=["喜欢历史"], domain=ResearchDomain.VISIT,
    )


class SequentialExclusionModel(AuthorizedPlanningModel):
    async def ainvoke(self, messages, **kwargs):
        payload = json.loads(messages[-1]["content"])
        if "clauses" not in payload:
            return await super().ainvoke(messages, **kwargs)
        self.normalization_calls += 1
        rows = []
        for clause in payload["clauses"]:
            text = clause["text"]
            constraints = []
            if "咖啡" in text:
                intent = {
                    "kind": "must_include", "target": "dining", "strength": "hard",
                    "priority": 90, "value": {"value_type": "category", "categories": ["咖啡"]},
                    "verification_mode": "mixed", "impact_stages": ["research", "composition"],
                    "public_summary": "优先研究咖啡",
                }
                constraints = [{"category": "dietary_restriction", "value": "不喝咖啡", "params": {}}]
            elif "博物馆" in text:
                intent = {
                    "kind": "must_exclude", "target": "visit", "strength": "hard",
                    "priority": 90, "value": {"value_type": "scalar", "value": "不去博物馆"},
                    "verification_mode": "mixed", "impact_stages": ["research", "composition"],
                    "public_summary": "不去博物馆",
                }
            else:
                intent = {
                    "kind": "objective", "target": "trip", "strength": "hard", "priority": 90,
                    "value": {"value_type": "scalar", "value": text},
                    "verification_mode": "mixed", "impact_stages": ["research", "composition"],
                    "public_summary": text,
                }
            rows.append({
                "clause_id": clause["clause_id"], "disposition": "mapped_to_intent",
                "reason_code": None, "intents": [intent], "constraints": constraints,
            })
        return json.dumps({"clauses": rows}, ensure_ascii=False)


async def test_exclusions_are_answered_one_by_one_and_never_become_queries(monkeypatch):
    model = SequentialExclusionModel()
    _install_planning_model(monkeypatch, model)
    graph = build_travel_workflow().compile(
        checkpointer=InMemorySaver(), interrupt_before=[NODE_DISPATCHER],
    )
    config = {"configurable": {"thread_id": "sequential-exclusions", "plan_gate_enabled": True}}
    first = await graph.ainvoke(TravelAgentState(
        run_id="sequential-exclusions", user_id="local",
        user_query="规划杭州旅行，不喝咖啡，不去博物馆",
        controlled_trip_identity=IDENTITY,
    ), config)
    first_gate = first["__interrupt__"][0].value
    assert first_gate["plan"]["steps"] == []
    first_object = "咖啡" if "咖啡" in first_gate["plan_text"] else "博物馆"
    second_object = "博物馆" if first_object == "咖啡" else "咖啡"

    second = await graph.ainvoke(Command(resume={
        "action": "supplement", "content": f"确认排除{first_object}",
        "approval_token": first_gate["approval_token"],
    }), config)
    second_gate = second["__interrupt__"][0].value
    assert second_gate["plan"]["steps"] == []
    assert second_object in second_gate["plan_text"]
    assert model.selection_calls == 0

    final = await graph.ainvoke(Command(resume={
        "action": "supplement", "content": f"确认排除{second_object}",
        "approval_token": second_gate["approval_token"],
    }), config)
    final_gate = final["__interrupt__"][0].value
    assert final_gate["plan"]["source"] == "model"
    query_text = " ".join(
        [query.query_text for query in final["research_query_plan"].queries]
        + [alias for query in final["research_query_plan"].queries for alias in query.aliases]
    )
    assert "咖啡" not in query_text
    assert "博物馆" not in query_text
    assert len(final["clarified_exclusion_keys"]) == 2


class AlwaysFailingPlanningModel(AuthorizedPlanningModel):
    async def ainvoke(self, messages, **kwargs):
        payload = json.loads(messages[-1]["content"])
        if "clauses" in payload:
            return await super().ainvoke(messages, **kwargs)
        self.selection_calls += 1
        raise RuntimeError("persistent offline selection failure")


async def test_research_plan_retry_stops_at_the_bounded_attempt_count(monkeypatch):
    model = AlwaysFailingPlanningModel()
    _install_planning_model(monkeypatch, model)
    weather = ApplicableWeather()
    graph = build_travel_workflow().compile(
        checkpointer=InMemorySaver(), interrupt_before=[NODE_DISPATCHER],
    )
    config = {"configurable": {
        "thread_id": "bounded-plan-retry", "plan_gate_enabled": True,
        "weather_context_builder": WeatherContextBuilder([weather], max_retries_per_provider=0),
    }}
    result = await graph.ainvoke(TravelAgentState(
        run_id="bounded-plan-retry", user_id="local", user_query="规划杭州旅行",
        controlled_trip_identity=IDENTITY,
    ), config)
    gate = result["__interrupt__"][0].value
    assert model.selection_calls == 1

    for expected_calls in (2, 3):
        result = await graph.ainvoke(Command(resume={
            "action": "retry", "approval_token": gate["approval_token"],
        }), config)
        gate = result["__interrupt__"][0].value
        assert model.selection_calls == expected_calls

    assert "retry" not in gate["decision_options"]
    assert gate["retry_available"] is False
    assert result["research_plan_retry_count"] == 2
    replay = await graph.ainvoke(Command(resume={
        "action": "retry", "approval_token": gate["approval_token"],
    }), config)
    assert replay["__interrupt__"]
    assert model.selection_calls == 3
    assert weather.calls == []


class IssueThenExclusionModel(SequentialExclusionModel):
    async def ainvoke(self, messages, **kwargs):
        payload = json.loads(messages[-1]["content"])
        if "clauses" not in payload or self.normalization_calls:
            return await super().ainvoke(messages, **kwargs)
        self.normalization_calls += 1
        rows = []
        for clause in payload["clauses"]:
            text = clause["text"]
            if "行动限制" in text:
                rows.append({
                    "clause_id": clause["clause_id"], "disposition": "unresolved",
                    "reason_code": "needs_clarification", "intents": [], "constraints": [],
                })
            elif "博物馆" in text:
                rows.append({
                    "clause_id": clause["clause_id"], "disposition": "mapped_to_intent",
                    "reason_code": None,
                    "intents": [{
                        "kind": "must_exclude", "target": "visit", "strength": "hard",
                        "priority": 90, "value": {"value_type": "scalar", "value": "不去博物馆"},
                        "verification_mode": "mixed", "impact_stages": ["research", "composition"],
                        "public_summary": "不去博物馆",
                    }],
                    "constraints": [],
                })
            else:
                rows.append({
                    "clause_id": clause["clause_id"], "disposition": "mapped_to_intent",
                    "reason_code": None,
                    "intents": [{
                        "kind": "objective", "target": "trip", "strength": "hard", "priority": 90,
                        "value": {"value_type": "scalar", "value": text},
                        "verification_mode": "mixed", "impact_stages": ["research", "composition"],
                        "public_summary": text,
                    }],
                    "constraints": [],
                })
        return json.dumps({"clauses": rows}, ensure_ascii=False)


async def test_answering_an_issue_does_not_mark_an_unshown_exclusion_as_answered(monkeypatch):
    model = IssueThenExclusionModel()
    _install_planning_model(monkeypatch, model)
    graph = build_travel_workflow().compile(
        checkpointer=InMemorySaver(), interrupt_before=[NODE_DISPATCHER],
    )
    config = {"configurable": {"thread_id": "issue-before-exclusion", "plan_gate_enabled": True}}
    first = await graph.ainvoke(TravelAgentState(
        run_id="issue-before-exclusion", user_id="local",
        user_query="长辈行动限制待明确，不去博物馆",
        controlled_trip_identity=IDENTITY,
    ), config)
    first_gate = first["__interrupt__"][0].value
    assert "行动限制" in first_gate["plan_text"]

    second = await graph.ainvoke(Command(resume={
        "action": "supplement", "content": "需要无障碍",
        "approval_token": first_gate["approval_token"],
    }), config)
    second_gate = second["__interrupt__"][0].value
    assert "博物馆" in second_gate["plan_text"]
    assert second["clarified_exclusion_keys"] == []
    assert model.selection_calls == 0
