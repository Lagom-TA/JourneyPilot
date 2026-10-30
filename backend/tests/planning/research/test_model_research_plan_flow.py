"""真实归一化 → 必要问答 / requirements_ready → 独立计划生成 → 计划门的离线链路。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from travel_agent.planning.delivery.minimum_draft import (
    minimum_delivery_draft_builder_node,
)
from travel_agent.planning.requirements import approval
from travel_agent.planning.requirements.constraints import loading
from travel_agent.planning.requirements.constraints.loading import (
    LoadedConstraintSources,
)
from travel_agent.planning.requirements.normalization import node as normalization
from travel_agent.planning.research import research_plan_node
from travel_agent.planning.research.brief_node import research_brief_builder_node
from travel_agent.planning.research.dispatch import dispatcher_node
from travel_agent.planning.research.operation_authority import (
    research_approval_confirmation_hash,
)
from travel_agent.planning.research.plan import planner_node
from travel_agent.planning.research.research_plan_node import (
    research_plan_generator_node,
)
from travel_agent.planning.state import TravelAgentState


def _place(name: str) -> dict:
    return {
        "place_id": f"offline:{name}",
        "provider": "osm",
        "kind": "city",
        "name": name,
        "display_name": name,
        "country_code": "CN",
        "latitude": 31.2,
        "longitude": 121.4,
        "admin_path": [],
    }


_IDENTITY = {
    "origin": _place("上海"),
    "destinations": [_place("杭州")],
    "start_date": "2026-11-05",
    "end_date": "2026-11-07",
    "party": {
        "adults": 2,
        "children": 0,
        "elderly_companions": False,
        "accessibility_required": True,
    },
    "style": {
        "primary": "建筑与本地文化",
        "secondary_interests": ["历史"],
        "source": "current",
    },
}

_ONE_DAY_IDENTITY = {
    **_IDENTITY,
    "end_date": "2026-11-05",
}


class _PlanningModel:
    """按 prompt 形状分流：clauses 走归一化，required_domains 只选授权候选 ID。"""

    capabilities = SimpleNamespace(supports_json_schema=False)

    def __init__(
        self,
        variant: str = "first",
        *,
        fail_selection_calls: tuple[int, ...] = (),
        overreach: str | None = None,
    ):
        self.variant = variant
        self.fail_selection_calls = set(fail_selection_calls)
        self.overreach = overreach
        self.normalization_calls = 0
        self.selection_calls = 0
        self.payloads: list[dict] = []
        self.selected_search_labels: list[str] = []

    async def ainvoke(self, messages, **_kwargs):
        payload = json.loads(messages[-1]["content"])
        if "clauses" in payload:
            self.normalization_calls += 1
            self.payloads.append(payload)
            return json.dumps(
                {
                    "clauses": [
                        self._clause_row(item) for item in payload["clauses"]
                    ]
                },
                ensure_ascii=False,
            )

        self.selection_calls += 1
        if self.selection_calls in self.fail_selection_calls:
            raise RuntimeError("offline selection failure")
        self.selected_search_labels = []
        domains = {}
        for domain in payload["required_domains"]:
            candidates = [
                item for item in payload["candidates"] if item["domain"] == domain
            ]
            selected = candidates[0] if self.variant == "first" else candidates[-1]
            self.selected_search_labels.append(selected["label"])
            domains[domain] = {
                "focus_candidate_ids": [selected["candidate_id"]],
                "search_candidate_ids": [selected["candidate_id"]],
            }
        return json.dumps({"domains": domains}, ensure_ascii=False)

    def _clause_row(self, clause: dict) -> dict:
        text = str(clause.get("text") or "")
        if self.overreach is not None and self.normalization_calls == 1:
            # 模型把未经用户说过的目的地、人数或日期写成 Intent 自由文本。
            injected = {
                "scalar": "顺便安排东京迪士尼、五人和十二月行程",
                "structured": "规划杭州行程，并加入东京迪士尼、五人和十二月",
            }[self.overreach]
            return _intent_row(
                clause,
                kind="objective",
                target="trip",
                value={"value_type": "scalar", "value": injected},
                summary=injected,
            )
        if "报告" in text and "简洁" in text:
            return _projection_row(clause, text=text)
        return _intent_row(
            clause,
            kind="objective",
            target="trip",
            value={"value_type": "scalar", "value": text},
            summary=text,
        )


def _intent_row(
    clause: dict,
    *,
    kind: str,
    target: str,
    value: dict,
    summary: str,
) -> dict:
    return {
        "clause_id": clause["clause_id"],
        "disposition": "mapped_to_intent",
        "reason_code": None,
        "intents": [
            {
                "kind": kind,
                "target": target,
                "strength": "hard",
                "priority": 90,
                "value": value,
                "verification_mode": "mixed",
                "impact_stages": ["research", "composition", "projection"],
                "public_summary": summary,
            }
        ],
        "constraints": [],
    }


def _projection_row(clause: dict, *, text: str) -> dict:
    row = _intent_row(
        clause,
        kind="attribute_preference",
        target="trip",
        value={"value_type": "scalar", "value": text},
        summary="报告输出要简洁",
    )
    row["intents"][0]["impact_stages"] = ["projection"]
    return row


class _Memory:
    async def get_user_profile(self, *_args, **_kwargs):
        return None

    async def list_manual_facts(self, *_args, **_kwargs):
        return []

    async def search_facts(self, *_args, **_kwargs):
        return []


def _profile():
    return SimpleNamespace(
        preferences=SimpleNamespace(
            travel_styles=[],
            dietary_restrictions=[],
            typical_budget_level="",
            accommodation_type="",
            pace="",
            preferred_transport=[],
        )
    )


async def _load_sources(_state):
    return LoadedConstraintSources(
        user_profile=_profile(),
        manual_memory_facts=[],
        manual_memory_truncated=False,
        memory_facts=[],
        missing_layers=[],
        partial_reasons=[],
    )


def _install_offline_boundaries(monkeypatch, model: _PlanningModel):
    monkeypatch.setattr(normalization, "load_constraint_sources", _load_sources)
    for module in (normalization, loading):
        monkeypatch.setattr(module, "get_model_router", lambda: object())
        monkeypatch.setattr(module, "llm_for_task", lambda *_args, **_kwargs: model)
    monkeypatch.setattr(loading, "UserProfileMemory", _Memory)
    monkeypatch.setattr(loading, "MemoryStore", _Memory)
    monkeypatch.setattr(research_plan_node, "get_model_router", lambda: object())
    monkeypatch.setattr(
        research_plan_node, "llm_for_task", lambda *_args, **_kwargs: model
    )


def _route_after_normalization(state: TravelAgentState) -> str:
    if state.request_contract_candidate is not None:
        return "plan_gate"
    return "brief"


def _graph():
    builder = StateGraph(TravelAgentState)
    for name, node in (
        ("request_contract_normalizer", normalization.request_contract_normalizer_node),
        ("research_plan_generator", research_plan_generator_node),
        ("brief", research_brief_builder_node),
        ("draft", minimum_delivery_draft_builder_node),
        ("planner", planner_node),
        ("plan_gate", approval.plan_gate_node),
        ("dispatcher", dispatcher_node),
    ):
        builder.add_node(name, node)
    builder.add_edge(START, "request_contract_normalizer")
    builder.add_conditional_edges(
        "request_contract_normalizer",
        _route_after_normalization,
        {"plan_gate": "plan_gate", "brief": "brief"},
    )
    builder.add_edge("research_plan_generator", "brief")
    builder.add_edge("brief", "draft")
    builder.add_edge("draft", "planner")
    builder.add_edge("planner", "plan_gate")
    builder.add_conditional_edges(
        "plan_gate",
        approval.route_after_plan_gate,
        {
            "request_contract_normalizer": "request_contract_normalizer",
            "research_plan_generator": "research_plan_generator",
            "dispatcher": "dispatcher",
        },
    )
    builder.add_edge("dispatcher", END)
    return builder.compile(checkpointer=InMemorySaver())


def _initial_state(
    run_id: str,
    *,
    user_query: str = "帮我规划杭州行程",
    identity: dict = _IDENTITY,
) -> TravelAgentState:
    return TravelAgentState(
        run_id=run_id,
        user_id="local",
        session_id=run_id,
        user_query=user_query,
        controlled_trip_identity=identity,
    )


def _config(run_id: str) -> dict:
    return {
        "configurable": {
            "thread_id": run_id,
            "plan_gate_enabled": True,
        }
    }


def _assert_operation_approval(result: dict, payload: dict) -> None:
    manifest = payload["_operation_manifest"]
    operation_approval = payload["_operation_approval"]
    expected = research_approval_confirmation_hash(
        result["request_contract"].content_hash, payload["approval_token"]
    )
    assert operation_approval.approval_token == payload["approval_token"]
    assert manifest.approval_token == payload["approval_token"]
    assert operation_approval.confirmation_hash == expected
    assert manifest.confirmation_hash == expected


def _query_text(result: dict) -> str:
    return " ".join(
        [
            *[query.query_text for query in result["research_query_plan"].queries],
            *[
                alias
                for query in result["research_query_plan"].queries
                for alias in query.aliases
            ],
        ]
    )


@pytest.mark.asyncio
async def test_two_model_plans_reach_the_confirmed_execution_identically(monkeypatch):
    observed = {}
    for variant in ("first", "second"):
        model = _PlanningModel(variant)
        _install_offline_boundaries(monkeypatch, model)
        graph = _graph()
        run_id = f"offline-model-plan-{variant}"
        confirmed = await graph.ainvoke(
            _initial_state(run_id), _config(run_id)
        )
        payload = confirmed["__interrupt__"][0].value

        assert payload.get("phase") is None
        assert payload["plan"]["source"] == "model"
        assert payload["revision"] == 0
        assert "approve" in payload["decision_options"]
        assert "**研究范围与检索词**" in payload["plan_text"]
        assert confirmed["request_contract"].research_plan is not None
        _assert_operation_approval(confirmed, payload)
        confirmed_query_ids = {
            query_id
            for assignment in confirmed["agent_assignments"].values()
            for query_id in assignment.get("research_query_ids", [])
        }
        confirmed_queries = {
            query.query_id: query
            for query in confirmed["research_query_plan"].queries
            if query.query_id in confirmed_query_ids
        }
        assert confirmed_queries
        assert payload["approval_token"].startswith("plan_gate.approval.v1:")
        assert model.normalization_calls == 1
        assert model.selection_calls == 1

        approved = await graph.ainvoke(
            Command(
                resume={
                    "action": "approve",
                    "approval_token": payload["approval_token"],
                }
            ),
            _config(run_id),
        )
        assert (
            approved["research_query_plan"].content_hash
            == confirmed["research_query_plan"].content_hash
        )
        assert approved["agent_assignments"] == confirmed["agent_assignments"]
        assert approved["planning_generation"] == confirmed["planning_generation"]
        assert approved["minimum_delivery_draft"].planning_authorized
        assert approved["research_operation_approval"] is not None
        assert model.normalization_calls == 1
        assert model.selection_calls == 1
        query_text = _query_text(approved)
        for label in model.selected_search_labels:
            assert label in query_text
        observed[variant] = (payload["plan"], query_text)

    first_plan, first_queries = observed["first"]
    second_plan, second_queries = observed["second"]
    assert first_plan["research_scope"] != second_plan["research_scope"]
    assert first_queries != second_queries


@pytest.mark.asyncio
async def test_display_only_edit_requires_a_fresh_approval_without_obsolete_state(
    monkeypatch,
):
    model = _PlanningModel("first")
    _install_offline_boundaries(monkeypatch, model)
    graph = _graph()
    run_id = "offline-model-plan-display-edit"
    config = _config(run_id)
    first = await graph.ainvoke(_initial_state(run_id), config)
    first_payload = first["__interrupt__"][0].value

    edited = await graph.ainvoke(
        Command(
            resume={
                "action": "supplement",
                "content": "报告更简洁",
                "approval_token": first_payload["approval_token"],
            }
        ),
        config,
    )
    second_payload = edited["__interrupt__"][0].value

    assert second_payload.get("phase") is None
    assert edited["planning_generation"] is not None
    assert second_payload["revision"] == 1
    assert second_payload["approval_token"] != first_payload["approval_token"]
    assert second_payload["plan"]["source"] == "model"
    assert second_payload["decision_options"] == ["approve", "cancel"]
    assert any(
        item["summary"] == "报告输出要简洁"
        for item in second_payload["recognized_requirements"]["hard"]
    )
    assert "报告输出要简洁" in edited["research_brief"].delivery_requirements
    assert (
        edited["research_query_plan"].content_hash
        != first["research_query_plan"].content_hash
    )
    assert model.normalization_calls == 2
    assert model.selection_calls == 2
    assert second_payload["plan"]["steps"]
    assert edited["request_contract"].research_plan is not None

    approved = await graph.ainvoke(
        Command(
            resume={
                "action": "approve",
                "approval_token": second_payload["approval_token"],
            }
        ),
        config,
    )
    assert approved["minimum_delivery_draft"].planning_authorized
    assert (
        approved["research_query_plan"].content_hash
        == edited["research_query_plan"].content_hash
    )
    state = TravelAgentState.model_validate(approved)
    assert state.plan_gate_decision["action"] == "approve"


@pytest.mark.asyncio
async def test_model_failure_has_a_real_retry_before_any_approval(monkeypatch):
    model = _PlanningModel("first", fail_selection_calls=(1,))
    _install_offline_boundaries(monkeypatch, model)
    graph = _graph()
    run_id = "offline-model-plan-retry"
    config = _config(run_id)
    failed = await graph.ainvoke(_initial_state(run_id), config)
    failed_payload = failed["__interrupt__"][0].value

    # 独立计划阶段的模型失败是显式重试门，不是可批准的计划。
    assert failed_payload["plan"]["steps"] == []
    assert "approve" not in failed_payload["decision_options"]
    assert "retry" in failed_payload["decision_options"]
    assert failed["request_contract"].research_plan is None
    assert model.normalization_calls == 1
    assert model.selection_calls == 1

    replay = await graph.ainvoke(
        Command(
            resume={
                "action": "approve",
                "approval_token": failed_payload["approval_token"],
            }
        ),
        config,
    )
    assert "retry" in replay["__interrupt__"][0].value["decision_options"]
    assert model.selection_calls == 1

    retried = await graph.ainvoke(
        Command(
            resume={
                "action": "retry",
                "approval_token": failed_payload["approval_token"],
            }
        ),
        config,
    )
    retried_payload = retried["__interrupt__"][0].value
    assert retried_payload["plan"]["source"] == "model"
    assert "approve" in retried_payload["decision_options"]
    assert model.normalization_calls == 1, "retry must not renormalize"
    assert model.selection_calls == 2


def _dining_contract():
    from travel_agent.planning.requirements.normalization.contracts import (
        IntentDraft,
        NormalizedClauseDraft,
        RequestContractNormalizationResult,
        SourceClause,
    )
    from travel_agent.planning.requirements.intent_contracts import (
        CategoryIntentValue,
        IntentKind,
        IntentStrength,
        IntentTarget,
        VerificationMode,
    )
    from travel_agent.planning.requirements.request_contracts import ClauseDisposition
    from travel_agent.planning.requirements.revision import (
        build_request_contract_revision,
    )
    from travel_agent.planning.requirements.research_plan_contracts import (
        ResearchDomainPlanDraft,
        ResearchPlanDraft,
    )

    clause = SourceClause(
        clause_id="clause_dining",
        source_ref_id="query_main",
        source_kind="current_request",
        source_text="找几家安静咖啡",
        span_start=0,
        span_end=8,
    )
    normalized = RequestContractNormalizationResult(
        clauses=[
            NormalizedClauseDraft(
                clause_id=clause.clause_id,
                disposition=ClauseDisposition.MAPPED_TO_INTENT,
                intents=[
                    IntentDraft(
                        kind=IntentKind.MUST_INCLUDE,
                        target=IntentTarget.DINING,
                        strength=IntentStrength.HARD,
                        priority=90,
                        value=CategoryIntentValue(categories=["咖啡"]),
                        verification_mode=VerificationMode.MIXED,
                        impact_stages=["research", "composition"],
                        public_summary="安排安静的咖啡店",
                    )
                ],
            )
        ],
        research_plan=ResearchPlanDraft(
            domains=[
                ResearchDomainPlanDraft(
                    domain="dining",
                    focus_atoms=["安静", "咖啡"],
                    search_terms=["安静 咖啡"],
                ),
                ResearchDomainPlanDraft(
                    domain="lodging",
                    focus_atoms=["安静", "住宿"],
                    search_terms=["安静 住宿"],
                ),
                ResearchDomainPlanDraft(
                    domain="long_distance_transport",
                    focus_atoms=["交通"],
                    search_terms=["往返 交通"],
                ),
                ResearchDomainPlanDraft(
                    domain="visit",
                    focus_atoms=["建筑", "文化"],
                    search_terms=["建筑 文化"],
                ),
            ],
        ),
    )
    return build_request_contract_revision(
        run_id="offline-amap-plan",
        identity=_IDENTITY,
        identity_revision=1,
        constraint_pack={
            "constraints": [],
            "hard_constraints": [],
            "soft_preferences": [],
            "pack_meta": {},
        },
        constraint_pack_revision=1,
        clauses=[clause],
        normalized=normalized,
        research_plan=normalized.research_plan,
    )[0]


@pytest.mark.asyncio
async def test_model_search_terms_are_the_real_amap_keywords(monkeypatch):
    from travel_agent.planning.research.brief_builder import build_research_brief
    from travel_agent.planning.research.destination import dining_binding
    from travel_agent.planning.research.destination import discovery
    from travel_agent.planning.research.destination.scope import (
        build_destination_boundaries,
    )
    from travel_agent.planning.research.query_contracts import ResearchQueryKind
    from travel_agent.planning.research.query_planner import build_research_query_plan

    contract = _dining_contract()
    brief = build_research_brief(contract, _IDENTITY)
    assert brief.research_plan_source == "model"
    query_plan = build_research_query_plan(
        intent_spec=contract.intent_spec, brief=brief
    )
    dining_structural = next(
        query
        for query in query_plan.queries
        if query.domain.value == "dining"
        and query.query_kind is ResearchQueryKind.STRUCTURAL
    )
    assert dining_structural.aliases == ["安静 咖啡"]

    calls = []

    async def _execute(name, arguments, **_kwargs):
        calls.append((name, arguments))
        return {
            "tool_name": "maps_text_search",
            "server_name": "amap-maps",
            "status": "success",
            "audit_id": "audit-amap-1",
            "retrieved_at": "2026-11-01T00:00:00+00:00",
            "sanitized_result": {
                "results": [
                    {
                        "id": "B0OFFLINE1",
                        "name": "安静咖啡馆",
                        "address": "杭州西湖区",
                        "typecode": "050500",
                        "latitude": 30.25,
                        "longitude": 120.16,
                    }
                ]
            },
        }

    monkeypatch.setattr(dining_binding, "execute_tool", _execute)
    executed: list[str] = []
    authoritative: list[dict] = []
    await discovery.discover_and_resolve_required_places(
        messages=[],
        available_tools=[{"schema": {"function": {"name": "maps_text_search"}}}],
        required_candidate_kinds=["dining"],
        destination_boundaries=build_destination_boundaries(_IDENTITY),
        tool_context={},
        authoritative_tool_results=authoritative,
        planned_queries=query_plan.queries,
        executed_query_ids=executed,
    )

    assert calls
    name, arguments = calls[0]
    assert name == "maps_text_search"
    assert arguments == {"keywords": "安静 咖啡", "city": "杭州"}
    assert dining_structural.query_id in executed
    assert authoritative


@pytest.mark.asyncio
async def test_model_dining_searches_each_destination_with_its_own_query(monkeypatch):
    from copy import deepcopy

    from travel_agent.planning.research.brief_builder import build_research_brief
    from travel_agent.planning.research.destination import dining_binding, discovery
    from travel_agent.planning.research.destination.scope import build_destination_boundaries
    from travel_agent.planning.research.query_planner import build_research_query_plan

    identity = deepcopy(_IDENTITY)
    identity["destinations"].append(_place("苏州"))
    contract = _dining_contract()
    brief = build_research_brief(contract, identity)
    plan = build_research_query_plan(intent_spec=contract.intent_spec, brief=brief)
    calls = []

    async def execute(name, arguments, **_kwargs):
        calls.append((name, arguments))
        return {
            "tool_name": name,
            "server_name": "amap-maps",
            "status": "success",
            "audit_id": "offline-" + arguments["city"],
            "retrieved_at": "2026-11-01T00:00:00+00:00",
            "sanitized_result": {"results": [{
                "id": "B0-" + arguments["city"],
                "name": "测试咖啡店",
                "address": arguments["city"],
                "typecode": "050500",
                "latitude": 31.2,
                "longitude": 121.4,
            }]},
        }

    monkeypatch.setattr(dining_binding, "execute_tool", execute)
    executed: list[str] = []
    await discovery.discover_and_resolve_required_places(
        messages=[],
        available_tools=[{"schema": {"function": {"name": "maps_text_search"}}}],
        required_candidate_kinds=["dining"],
        destination_boundaries=build_destination_boundaries(identity),
        tool_context={},
        authoritative_tool_results=[],
        planned_queries=plan.queries,
        executed_query_ids=executed,
    )
    assert {arguments["city"] for _, arguments in calls} == {"杭州", "苏州"}
    assert all(arguments["keywords"] == "安静 咖啡" for _, arguments in calls)
    expected = {
        query.query_id for query in plan.queries
        if query.domain.value == "dining" and query.query_kind.value == "structural"
    }
    assert expected <= set(executed)


@pytest.mark.asyncio
async def test_multidestination_web_discovery_handles_no_queries(monkeypatch):
    from copy import deepcopy

    from travel_agent.planning.research.destination import discovery
    from travel_agent.planning.research.destination.scope import build_destination_boundaries

    identity = deepcopy(_IDENTITY)
    identity["destinations"].append(_place("苏州"))
    calls = []

    async def execute(*args, **kwargs):
        calls.append((args, kwargs))
        return {}

    monkeypatch.setattr(discovery, "execute_tool", execute)
    await discovery.discover_and_resolve_required_places(
        messages=[],
        available_tools=[{"schema": {"function": {"name": "free_web_search"}}}],
        required_candidate_kinds=["dining"],
        destination_boundaries=build_destination_boundaries(identity),
        tool_context={},
        authoritative_tool_results=[],
        planned_queries=[],
        executed_query_ids=[],
    )
    assert calls == []


# --- 复审反例：饮食禁忌必须由本次请求重新明确后进入检索 -------------------


class _DietaryModel(_PlanningModel):
    """历史画像写明「不吃牛肉」；当前请求只提到小吃。"""

    def _clause_row(self, clause: dict) -> dict:
        text = str(clause.get("text") or "")
        if "不吃牛肉" in text:
            row = _intent_row(
                clause,
                kind="objective",
                target="trip",
                value={"value_type": "scalar", "value": text},
                summary=text,
            )
            row["disposition"] = "mapped_to_constraint"
            row["intents"] = []
            row["constraints"] = [
                {"category": "dietary_restriction", "value": "不吃牛肉", "params": {}},
                {
                    "category": "food_allergy",
                    "value": "不吃牛肉",
                    "params": {"allergens": ["牛肉"]},
                },
            ]
            return row
        if "小吃" in text:
            return _intent_row(
                clause,
                kind="must_include",
                target="dining",
                value={"value_type": "category", "categories": ["小吃"]},
                summary="找当地小吃",
            )
        return _intent_row(
            clause,
            kind="objective",
            target="trip",
            value={"value_type": "scalar", "value": text},
            summary=text,
        )


def _dietary_profile():
    return SimpleNamespace(
        preferences=SimpleNamespace(
            travel_styles=[],
            dietary_restrictions=["不吃牛肉"],
            typical_budget_level="",
            accommodation_type="",
            pace="",
            preferred_transport=[],
        )
    )


@pytest.mark.asyncio
async def test_dietary_restriction_cannot_become_a_provider_search_term(monkeypatch):
    model = _DietaryModel()
    _install_offline_boundaries(monkeypatch, model)

    async def _load_dietary_sources(_state):
        return LoadedConstraintSources(
            user_profile=_dietary_profile(),
            manual_memory_facts=[],
            manual_memory_truncated=False,
            memory_facts=[],
            missing_layers=[],
            partial_reasons=[],
        )

    monkeypatch.setattr(
        normalization, "load_constraint_sources", _load_dietary_sources
    )
    graph = _graph()
    run_id = "offline-dietary-restriction"
    config = _config(run_id)
    before = await graph.ainvoke(
        _initial_state(
            run_id,
            user_query="帮我规划杭州一日游，想吃点小吃",
            identity=_ONE_DAY_IDENTITY,
        ),
        config,
    )
    initial = before["__interrupt__"][0].value

    # 历史画像里的禁忌不属于本次授权；它不会被静默执行，也不会进入检索。
    assert initial.get("phase") is None
    assert initial["plan"]["source"] == "model"
    initial_text = " ".join(
        [
            initial["plan_text"],
            json.dumps(initial["plan"]["research_scope"], ensure_ascii=False),
            _query_text(before),
            json.dumps(before["agent_assignments"], ensure_ascii=False),
        ]
    )
    assert "牛肉" not in initial_text
    assert "小吃" in _query_text(before)
    assert model.normalization_calls == 1
    assert model.selection_calls == 1

    clarified = await graph.ainvoke(
        Command(
            resume={
                "action": "supplement",
                "content": "饮食上不吃牛肉",
                "approval_token": initial["approval_token"],
            }
        ),
        config,
    )
    question = clarified["__interrupt__"][0].value
    # 当前请求重新明确禁忌后，仍先确认它是排除项而不是研究方向。
    assert question["plan"]["steps"] == []
    assert "牛肉" in question["plan_text"]
    assert "approve" not in question["decision_options"]
    assert model.normalization_calls == 2

    confirmed = await graph.ainvoke(
        Command(
            resume={
                "action": "supplement",
                "content": "是的，要避开牛肉",
                "approval_token": question["approval_token"],
            }
        ),
        config,
    )
    payload = confirmed["__interrupt__"][0].value
    assert payload["plan"]["steps"], (
        "dietary exclusion confirmation must resume planning instead of asking again"
    )
    assert payload["plan"]["source"] == "model"
    assert "牛肉" not in payload["plan_text"]
    scope_text = json.dumps(payload["plan"]["research_scope"], ensure_ascii=False)
    assert "牛肉" not in scope_text

    executed_text = _query_text(confirmed)
    assert "牛肉" not in executed_text
    assert "小吃" in executed_text  # 正向要求仍然被真正研究
    assert model.normalization_calls == 3
    assert model.selection_calls == 2

    approved = await graph.ainvoke(
        Command(
            resume={
                "action": "approve",
                "approval_token": payload["approval_token"],
            }
        ),
        config,
    )
    assert approved["minimum_delivery_draft"].planning_authorized
    assert approved["research_operation_approval"] is not None

    # 批准后真实走到餐饮检索工具：Provider 参数里也不能出现禁忌词。
    from travel_agent.planning.research.destination import dining_binding
    from travel_agent.planning.research.destination import discovery
    from travel_agent.planning.research.destination.scope import (
        build_destination_boundaries,
    )

    calls = []

    async def _execute(name, arguments, **_kwargs):
        calls.append((name, arguments))
        return {
            "tool_name": "maps_text_search",
            "server_name": "amap-maps",
            "status": "success",
            "audit_id": "audit-amap-dietary",
            "retrieved_at": "2026-11-01T00:00:00+00:00",
            "sanitized_result": {"results": []},
        }

    monkeypatch.setattr(dining_binding, "execute_tool", _execute)
    await discovery.discover_and_resolve_required_places(
        messages=[],
        available_tools=[{"schema": {"function": {"name": "maps_text_search"}}}],
        required_candidate_kinds=["dining"],
        destination_boundaries=build_destination_boundaries(_ONE_DAY_IDENTITY),
        tool_context={},
        authoritative_tool_results=[],
        planned_queries=approved["research_query_plan"].queries,
        executed_query_ids=[],
    )
    assert calls
    for _name, arguments in calls:
        assert "牛肉" not in json.dumps(arguments, ensure_ascii=False)


# --- 复审反例：模型 Intent 引入未授权目的地/人数/日期 ---------------------


_OVERREACH_TOKENS = ("东京", "大阪", "五日", "五人", "十二月", "迪士尼")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["scalar", "structured"])
async def test_model_cannot_add_unauthorized_place_party_or_dates(monkeypatch, mode):
    model = _PlanningModel(overreach=mode)
    _install_offline_boundaries(monkeypatch, model)
    graph = _graph()
    run_id = f"offline-overreach-{mode}"
    config = _config(run_id)
    before = await graph.ainvoke(_initial_state(run_id), config)
    clarification = before["__interrupt__"][0].value

    # 模型自由文本无法在用户原文逐字定位：先澄清，不能进入可批准计划。
    assert clarification["plan"]["steps"] == []
    assert "approve" not in clarification["decision_options"]
    assert "需要先补充" in clarification["plan_text"]
    assert before.get("research_query_plan") is None
    assert model.selection_calls == 0

    replay = await graph.ainvoke(
        Command(
            resume={
                "action": "approve",
                "approval_token": clarification["approval_token"],
            }
        ),
        config,
    )
    assert "approve" not in replay["__interrupt__"][0].value["decision_options"]
    assert model.selection_calls == 0

    corrected = await graph.ainvoke(
        Command(
            resume={
                "action": "supplement",
                "content": "请按我原来的杭州行程安排",
                "approval_token": clarification["approval_token"],
            }
        ),
        config,
    )
    payload = corrected["__interrupt__"][0].value

    confirmed_text = " ".join(
        [
            payload["plan_text"],
            *[
                str(task)
                for step in payload["plan"]["steps"]
                for task in step["tasks"].values()
            ],
            *[row["focus"] for row in payload["plan"]["research_scope"]],
            *[
                term
                for row in payload["plan"]["research_scope"]
                for term in row["search_terms"]
            ],
            _query_text(corrected),
        ]
    )
    for token in _OVERREACH_TOKENS:
        assert token not in confirmed_text

    approved = await graph.ainvoke(
        Command(
            resume={
                "action": "approve",
                "approval_token": payload["approval_token"],
            }
        ),
        config,
    )
    assert approved["minimum_delivery_draft"].planning_authorized
    executed = " ".join(
        [
            *[query.query_text for query in approved["research_query_plan"].queries],
            *[
                json.dumps(assignment, ensure_ascii=False)
                for assignment in approved["agent_assignments"].values()
            ],
        ]
    )
    for token in _OVERREACH_TOKENS:
        assert token not in executed


# --- 复审反例：旧无 token 的确认门 -------------------------------------


@pytest.mark.asyncio
async def test_missing_approval_token_replays_gate_without_model(monkeypatch):
    model = _PlanningModel("first")
    _install_offline_boundaries(monkeypatch, model)
    graph = _graph()
    run_id = "offline-legacy-gate"
    config = _config(run_id)
    before = await graph.ainvoke(_initial_state(run_id), config)
    first_payload = before["__interrupt__"][0].value
    assert first_payload.get("phase") is None
    assert model.normalization_calls == 1
    assert model.selection_calls == 1

    # 决策缺少版本凭据：重新展示同一最终门，而不是执行该决定。
    replayed = await graph.ainvoke(
        Command(resume={"action": "approve"}), config
    )
    replay_payload = replayed["__interrupt__"][0].value

    assert replay_payload["approval_token"].startswith("plan_gate.approval.v1:")
    assert replay_payload["approval_token"] == first_payload["approval_token"]
    assert replay_payload.get("phase") is None
    assert model.normalization_calls == 1
    assert model.selection_calls == 1, "re-display must not call the plan model"
    assert replay_payload["plan"]["source"] == "model"
    assert replay_payload["plan"]["steps"]

    approved = await graph.ainvoke(
        Command(
            resume={
                "action": "approve",
                "approval_token": replay_payload["approval_token"],
            }
        ),
        config,
    )
    assert approved["minimum_delivery_draft"].planning_authorized
    assert model.normalization_calls == 1
    assert model.selection_calls == 1


@pytest.mark.asyncio
async def test_missing_approval_token_allows_supplement_after_replay(monkeypatch):
    model = _PlanningModel("first")
    _install_offline_boundaries(monkeypatch, model)
    graph = _graph()
    run_id = "offline-legacy-gate-supplement"
    config = _config(run_id)
    await graph.ainvoke(_initial_state(run_id), config)

    replay = await graph.ainvoke(
        Command(resume={"action": "supplement", "content": "报告更简洁"}),
        config,
    )
    replay_payload = replay["__interrupt__"][0].value
    assert model.normalization_calls == 1
    assert model.selection_calls == 1
    assert replay_payload["approval_token"].startswith("plan_gate.approval.v1:")

    edited = await graph.ainvoke(
        Command(
            resume={
                "action": "supplement",
                "content": "报告更简洁",
                "approval_token": replay_payload["approval_token"],
            }
        ),
        config,
    )
    edited_payload = edited["__interrupt__"][0].value
    assert model.normalization_calls == 2
    assert model.selection_calls == 2
    assert edited_payload["plan"]["source"] == "model"
    assert edited_payload["revision"] == 1
    assert edited_payload["approval_token"] != replay_payload["approval_token"]
    assert any(
        item["summary"] == "报告输出要简洁"
        for item in edited_payload["recognized_requirements"]["hard"]
    )
