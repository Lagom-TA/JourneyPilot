
import asyncio
import json
from types import SimpleNamespace

import pytest
from openai import OpenAIError

import travel_agent.planning.requirements.normalization.model as _owner_planning_requirements_normalization_model
from travel_agent.planning.requirements.amendments import apply_runtime_amendments
from travel_agent.planning.requirements.approval import _build_plan_gate_payload
from travel_agent.planning.requirements.conflicts import detect_intent_conflicts
from travel_agent.planning.requirements.constraints.extraction import (
    deterministic_budget_constraints,
)
from travel_agent.planning.requirements.intent_contracts import (
    AlternativeIntentValue,
    CategoryIntentValue,
    IntentConflict,
    IntentItem,
    IntentKind,
    IntentStrength,
    IntentTarget,
    OutputRequirementValue,
    ScalarIntentValue,
    UnresolvedClause,
    VerificationMode,
)
from travel_agent.planning.requirements.normalization.clauses import (
    is_material_clause,
    split_source_clauses,
)
from travel_agent.planning.requirements.normalization.contracts import (
    IntentDraft,
    NormalizedClauseDraft,
    RequestContractNormalizationResult,
    SourceClause,
)
from travel_agent.planning.requirements.normalization.model import normalize_clauses
from travel_agent.planning.requirements.request_contracts import (
    ClauseDisposition,
    IntentAmendment,
)
from travel_agent.planning.requirements.revision import build_request_contract_revision
from travel_agent.planning.requirements.research_plan_contracts import (
    ResearchDomainPlanDraft,
    ResearchPlanDraft,
)
from travel_agent.planning.research.brief_builder import build_research_brief
from travel_agent.planning.research.capability_planning import build_capability_plan
from travel_agent.planning.research.dispatch import dispatcher_node, route_after_dispatcher
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.history import _latest_packets
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.planning.research.query_contracts import ResearchQueryKind
from travel_agent.planning.research.query_planner import build_research_query_plan
from travel_agent.planning.state import TravelAgentState


def _identity():
    return {
        "origin": {
            "place_id": "origin_shanghai",
            "provider": "manual_verified",
            "kind": "city",
            "name": "上海",
            "display_name": "上海",
            "country_code": "CN",
            "latitude": 31.2304,
            "longitude": 121.4737,
            "admin_path": ["上海"],
        },
        "destinations": [
            {
                "place_id": "destination_hangzhou",
                "provider": "manual_verified",
                "kind": "city",
                "name": "杭州",
                "display_name": "杭州",
                "country_code": "CN",
                "latitude": 30.2741,
                "longitude": 120.1551,
                "admin_path": ["浙江", "杭州"],
            }
        ],
        "start_date": "2026-09-01",
        "end_date": "2026-09-03",
        "party": {
            "adults": 2,
            "children": 0,
            "elderly_companions": False,
            "accessibility_required": False,
        },
        "style": {
            "primary": "建筑与本地文化",
            "secondary_interests": ["咖啡"],
            "source": "current",
        },
    }


def _clause(index: int, text: str, source_kind: str = "current_request"):
    return SourceClause(
        clause_id=f"clause_{index}",
        source_ref_id="query_main" if source_kind == "current_request" else "command_1",
        source_kind=source_kind,
        source_text=text,
        span_start=index * 20,
        span_end=index * 20 + len(text),
    )


def _intent(
    kind: IntentKind,
    target: IntentTarget,
    value,
    summary: str,
    stages: list[str],
):
    return IntentDraft(
        kind=kind,
        target=target,
        strength=IntentStrength.HARD,
        priority=90,
        value=value,
        verification_mode=VerificationMode.MIXED,
        impact_stages=stages,
        public_summary=summary,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("supports_native_schema", [False, True])
async def test_normalizer_projects_one_schema_by_provider_capability(
    supports_native_schema,
):
    clause = _clause(0, "2名成人")

    class _Model:
        capabilities = SimpleNamespace(supports_json_schema=supports_native_schema)

        def __init__(self):
            self.response_format = None
            self.max_output_tokens = None
            self.messages = None

        async def ainvoke(self, messages, **kwargs):
            self.messages = messages
            self.response_format = kwargs["response_format"]
            self.max_output_tokens = kwargs.get("max_output_tokens")
            return json.dumps(
                {
                    "clauses": [
                        {
                            "clause_id": clause.clause_id,
                            "disposition": "controlled_identity",
                        }
                    ]
                }
            )

    model = _Model()
    await normalize_clauses(
        clauses=[clause], controlled_identity=_identity(), llm=model
    )

    wrapper = model.response_format["json_schema"]
    assert model.max_output_tokens is None
    assert wrapper["strict"] is supports_native_schema
    clause_array = wrapper["schema"]["properties"]["clauses"]
    assert clause_array["minItems"] == clause_array["maxItems"] == 1
    assert wrapper["schema"]["$defs"]["NormalizedClauseDraft"]["properties"][
        "clause_id"
    ]["enum"] == [clause.clause_id]
    assert "value_type" in model.messages[0]["content"]
    assert "禁止 intent_type 或 type" in model.messages[0]["content"]
    assert "target=long_distance_transport" in model.messages[0]["content"]
    params_schema = wrapper["schema"]["$defs"]["ConstraintParamsDraft"]
    if supports_native_schema:
        assert "amount" in params_schema["required"]
    else:
        assert "required" not in params_schema


@pytest.mark.asyncio
async def test_slow_normalization_call_is_cancelled_and_falls_back_once(monkeypatch):

    clause = _clause(0, "并给出备选方案")

    class _Model:
        capabilities = SimpleNamespace(supports_json_schema=False)

        def __init__(self):
            self.calls = 0

        async def ainvoke(self, *_args, **_kwargs):
            self.calls += 1
            await asyncio.sleep(1)
            raise AssertionError("call timeout must cancel the slow call")

    monkeypatch.setattr(
        _owner_planning_requirements_normalization_model,
        "INTENT_NORMALIZATION_CALL_TIMEOUT_SECONDS",
        0.02,
    )
    model = _Model()

    result = await normalize_clauses(
        clauses=[clause],
        controlled_identity=_identity(),
        llm=model,
    )

    assert model.calls == 1
    [intent] = result.clauses[0].intents
    assert intent.kind is IntentKind.ALTERNATIVES
    assert intent.strength is IntentStrength.HARD


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_root",
    [
        lambda rows: {
            "clauses": rows,
            "summary": "provider-added metadata is not semantic authority",
        },
        lambda rows: rows,
    ],
)
async def test_normalizer_accepts_only_typed_rows_from_provider_root_variants(
    provider_root,
):
    clause = _clause(0, "并给出备选方案")

    class _Model:
        capabilities = SimpleNamespace(supports_json_schema=False)

        async def ainvoke(self, *_args, **_kwargs):
            rows = [
                {
                    "clause_id": clause.clause_id,
                    "disposition": "mapped_to_intent",
                    "intents": [
                        {
                            "kind": "alternatives",
                            "target": "delivery",
                            "strength": "hard",
                            "priority": 90,
                            "value": {
                                "value_type": "alternative",
                                "count": 2,
                            },
                            "verification_mode": "semantic",
                            "impact_stages": ["composition", "projection"],
                            "public_summary": "提供备选方案",
                        }
                    ],
                }
            ]
            return json.dumps(provider_root(rows))

    result = await normalize_clauses(
        clauses=[clause], controlled_identity=_identity(), llm=_Model()
    )

    [intent] = result.clauses[0].intents
    assert intent.kind is IntentKind.ALTERNATIVES
    assert intent.target is IntentTarget.DELIVERY


def _contract():
    clauses = [
        _clause(0, "帮我规划杭州行程"),
        _clause(1, "不要连锁咖啡"),
        _clause(2, "每个景点说明选择理由"),
        _clause(3, "给两套方案"),
    ]
    normalized = RequestContractNormalizationResult(
        clauses=[
            NormalizedClauseDraft(
                clause_id="clause_0",
                disposition=ClauseDisposition.MAPPED_TO_INTENT,
                intents=[
                    _intent(
                        IntentKind.OBJECTIVE,
                        IntentTarget.TRIP,
                        ScalarIntentValue(value="规划杭州可执行行程"),
                        "规划杭州可执行行程",
                        ["research", "composition", "projection"],
                    )
                ],
            ),
            NormalizedClauseDraft(
                clause_id="clause_1",
                disposition=ClauseDisposition.MAPPED_TO_INTENT,
                intents=[
                    _intent(
                        IntentKind.MUST_EXCLUDE,
                        IntentTarget.DINING,
                        CategoryIntentValue(categories=["连锁咖啡"]),
                        "排除连锁咖啡",
                        ["research", "composition"],
                    )
                ],
            ),
            NormalizedClauseDraft(
                clause_id="clause_2",
                disposition=ClauseDisposition.MAPPED_TO_INTENT,
                intents=[
                    _intent(
                        IntentKind.OUTPUT_REQUIREMENT,
                        IntentTarget.DELIVERY,
                        OutputRequirementValue(
                            required_field="景点选择理由",
                            applies_to="each_item",
                        ),
                        "每个景点说明选择理由",
                        ["projection"],
                    )
                ],
            ),
            NormalizedClauseDraft(
                clause_id="clause_3",
                disposition=ClauseDisposition.MAPPED_TO_INTENT,
                intents=[
                    _intent(
                        IntentKind.ALTERNATIVES,
                        IntentTarget.DELIVERY,
                        AlternativeIntentValue(count=2),
                        "交付两套可区分方案",
                        ["composition", "projection"],
                    )
                ],
            ),
        ]
    )
    return build_request_contract_revision(
        run_id="run_intent_contract",
        identity=_identity(),
        identity_revision=1,
        constraint_pack={
            "constraints": [],
            "hard_constraints": [],
            "soft_preferences": [],
            "pack_meta": {},
        },
        constraint_pack_revision=1,
        clauses=clauses,
        normalized=normalized,
    )


def _model_research_plan(
    terms: tuple[str, str, str],
    *,
    focus_atoms: tuple[str, str, str] = ("住宿", "交通", "建筑"),
):
    """一份结构合法的 fake 研究计划：只给可回溯的关注点和检索词。"""

    return ResearchPlanDraft(
        domains=[
            ResearchDomainPlanDraft(
                domain=ResearchDomain.LODGING,
                focus_atoms=[focus_atoms[0]],
                search_terms=[terms[0]],
            ),
            ResearchDomainPlanDraft(
                domain=ResearchDomain.LONG_DISTANCE_TRANSPORT,
                focus_atoms=[focus_atoms[1]],
                search_terms=[terms[1]],
            ),
            ResearchDomainPlanDraft(
                domain=ResearchDomain.VISIT,
                focus_atoms=[focus_atoms[2]],
                search_terms=[terms[2]],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_unsolicited_research_plan_is_ignored_during_clause_normalization():
    clause = _clause(0, "帮我规划杭州行程")

    class _Model:
        capabilities = SimpleNamespace(supports_json_schema=False)

        async def ainvoke(self, *_args, **_kwargs):
            return json.dumps(
                {
                    "clauses": [
                        {
                            "clause_id": clause.clause_id,
                            "disposition": "mapped_to_intent",
                            "intents": [
                                {
                                    "kind": "objective",
                                    "target": "trip",
                                    "strength": "hard",
                                    "priority": 90,
                                    "value": {
                                        "value_type": "scalar",
                                        "value": "规划杭州可执行行程",
                                    },
                                    "verification_mode": "mixed",
                                    "impact_stages": [
                                        "research",
                                        "composition",
                                        "projection",
                                    ],
                                    "public_summary": "规划杭州可执行行程",
                                }
                            ],
                        }
                    ],
                    "research_plan": {
                        "domains": [
                            {
                                "domain": "visit",
                                "focus_atoms": ["建筑", "文化"],
                                "search_terms": ["建筑 文化"],
                            },
                            {
                                "domain": "lodging",
                                "focus_atoms": ["住宿"],
                                "search_terms": ["杭州 地铁 住宿"],
                            },
                            {
                                "domain": "long_distance_transport",
                                "focus_atoms": ["交通"],
                                "search_terms": ["上海 杭州 高铁"],
                            },
                        ],
                    },
                },
                ensure_ascii=False,
            )

    result = await normalize_clauses(
        clauses=[clause], controlled_identity=_identity(), llm=_Model()
    )

    assert result.research_plan is None
    contract, generation = build_request_contract_revision(
        run_id="run_model_plan_normalizer",
        identity=_identity(),
        identity_revision=1,
        constraint_pack={
            "constraints": [],
            "hard_constraints": [],
            "soft_preferences": [],
            "pack_meta": {},
        },
        constraint_pack_revision=1,
        clauses=[clause],
        normalized=result,
        research_plan=result.research_plan,
    )
    assert contract.research_plan is None
    brief = build_research_brief(contract, _identity())
    queries = build_research_query_plan(
        intent_spec=contract.intent_spec, brief=brief
    )
    plan = build_capability_plan(
        request_contract=contract,
        brief=brief,
        plan_revision=generation.plan_revision,
        research_query_plan=queries,
    )
    assert brief.research_plan_source == "deterministic_fallback"
    assert all(
        "建筑 文化" not in query.query_text
        for query in queries.queries
        if query.domain is ResearchDomain.VISIT
        and query.query_kind is ResearchQueryKind.STRUCTURAL
    )
    assert "检索词：建筑 文化" not in plan.assignments[
        "destination_researcher"
    ].objective


@pytest.mark.asyncio
async def test_model_plan_is_discarded_when_clause_rows_need_fallback():
    clause = _clause(0, "并给出备选方案")

    class _Model:
        capabilities = SimpleNamespace(supports_json_schema=False)

        async def ainvoke(self, *_args, **_kwargs):
            return json.dumps(
                {
                    "clauses": [],
                    "research_plan": {
                        "domains": [
                            {
                                "domain": "visit",
                                "focus_atoms": ["景点"],
                                "search_terms": ["景点"],
                            }
                        ],
                    },
                },
                ensure_ascii=False,
            )

    result = await normalize_clauses(
        clauses=[clause], controlled_identity=_identity(), llm=_Model()
    )

    assert result.research_plan is None
    assert result.clauses[0].intents


def test_contract_and_capability_plan_are_deterministic_and_cover_hard_intents():
    contract, generation = _contract()
    repeated, repeated_generation = _contract()

    assert contract.content_hash == repeated.content_hash
    assert generation == repeated_generation
    assert len(contract.clause_ledger) == 4
    assert not contract.has_unresolved_material_clauses

    brief = build_research_brief(contract, _identity())
    query_plan = build_research_query_plan(
        intent_spec=contract.intent_spec,
        brief=brief,
    )
    plan = build_capability_plan(
        request_contract=contract,
        brief=brief,
        plan_revision=generation.plan_revision,
        research_query_plan=query_plan,
    )
    hard_ids = {
        item.intent_id
        for item in contract.intent_spec.active_items
        if item.strength is IntentStrength.HARD
    }
    owned_ids = {
        intent_id
        for assignment in plan.assignments.values()
        for intent_id in assignment.must_cover_intent_ids
    }
    assert hard_ids == owned_ids
    assert plan.execution_plan[-1] == ["itinerary_planner"]
    assert all(
        assignment.generation_id == generation.generation_id
        for assignment in plan.assignments.values()
    )
    assert {
        query_id
        for assignment in plan.assignments.values()
        for query_id in assignment.research_query_ids
    } == set(query_plan.query_index())
    public_tasks = " ".join(assignment.objective for assignment in plan.assignments.values())
    assert "责任" not in public_tasks
    assert (
        "在杭州（2026-09-01 至 2026-09-03，2 位成人，建筑与本地文化（咖啡））"
        "查找覆盖 2 晚的住宿选择"
    ) in public_tasks
    assert "查找上海 → 杭州 → 上海 的往返及跨城交通" in public_tasks
    assert (
        "为杭州 2026-09-01 至 2026-09-03（2 位成人，建筑与本地文化（咖啡））"
        "组合可执行按天路线"
    ) in public_tasks
    assert "查找覆盖整个行程的住宿选择" not in public_tasks


def test_deterministic_fallback_plan_text_names_the_actual_trip():
    contract, generation = _contract()
    brief, _queries, plan = _research_plan(contract, _identity(), generation)
    assert brief.research_plan_source == "deterministic_fallback"

    payload = _build_plan_gate_payload(
        SimpleNamespace(
            execution_plan=plan.execution_plan,
            agent_assignments={
                key: value.model_dump(mode="json")
                for key, value in plan.assignments.items()
            },
            controlled_trip_identity=_identity(),
            intent_spec=contract.intent_spec,
            constraint_pack={},
            research_brief=brief,
            research_query_plan=None,
            plan_gate_revision_count=0,
        )
    )
    text = payload["plan_text"]
    assert "**本次旅行**" in text
    assert "从上海出发，按杭州的顺序" in text
    assert "2026-09-01 至 2026-09-03" in text and "2 位成人" in text
    assert "建筑与本地文化（咖啡）" in text
    assert "上海 → 杭州 → 上海" in text
    assert "查找符合主题和要求的景点与体验" not in text
    assert "查找覆盖整个行程的住宿选择" not in text
    assert "结合候选目录与用户要求组合可执行按天行程" not in text


def test_explicit_baseline_intake_selection_survives_a_normalizer_miss():
    contract, _generation = _contract()
    brief = build_research_brief(contract, _identity())
    state = _model_plan_payload_state(contract, brief)
    state.intake_evidence_sources = [
        {
            "source_id": "source_food",
            "kind": "explicit_selection",
            "field": "answer:baseline_priorities:local_food",
            "text": "当地美食",
        },
        {
            "source_id": "source_default",
            "kind": "explicit_supplement",
            "field": "answer:baseline_priorities:sensible_default",
            "text": "按合理默认安排，不再补充",
        },
        {
            "source_id": "source_budget",
            "kind": "explicit_selection",
            "field": "answer:budget_scope:all",
            "text": "包含往返交通和住宿",
        },
    ]

    payload = _build_plan_gate_payload(state)
    summaries = [
        item["summary"] for item in payload["recognized_requirements"]["preferences"]
    ]
    assert "当地美食" in summaries
    assert "按合理默认安排，不再补充" not in summaries
    assert "包含往返交通和住宿" not in summaries


def _contract_with_extra_intents(*items):
    contract, generation = _contract()
    contract = contract.model_copy(
        update={
            "intent_spec": contract.intent_spec.model_copy(
                update={
                    "active_items": [
                        *contract.intent_spec.active_items,
                        *items,
                    ]
                }
            )
        }
    )
    return contract, generation


def _research_plan(contract, identity, generation):
    brief = build_research_brief(contract, identity)
    queries = build_research_query_plan(
        intent_spec=contract.intent_spec, brief=brief
    )
    plan = build_capability_plan(
        request_contract=contract,
        brief=brief,
        plan_revision=generation.plan_revision,
        research_query_plan=queries,
    )
    return brief, queries, plan


def test_model_research_plan_drives_contract_projection_and_execution_deterministically():
    contract, generation = _contract()
    first_contract = contract.model_copy(
        update={
            "research_plan": _model_research_plan(
                ("安静 住宿", "往返 交通", "建筑 文化")
            )
        }
    )
    second_contract = contract.model_copy(
        update={
            "research_plan": _model_research_plan(
                ("地铁 住宿", "车次 交通", "本地文化"),
                focus_atoms=("住宿", "交通", "文化"),
            )
        }
    )

    first_brief = build_research_brief(first_contract, _identity())
    first_queries = build_research_query_plan(
        intent_spec=first_contract.intent_spec, brief=first_brief
    )
    first_plan = build_capability_plan(
        request_contract=first_contract,
        brief=first_brief,
        plan_revision=generation.plan_revision,
        research_query_plan=first_queries,
    )
    repeated_brief = build_research_brief(first_contract, _identity())
    repeated_queries = build_research_query_plan(
        intent_spec=first_contract.intent_spec, brief=repeated_brief
    )
    repeated_plan = build_capability_plan(
        request_contract=first_contract,
        brief=repeated_brief,
        plan_revision=generation.plan_revision,
        research_query_plan=repeated_queries,
    )
    second_brief = build_research_brief(second_contract, _identity())
    second_queries = build_research_query_plan(
        intent_spec=second_contract.intent_spec, brief=second_brief
    )

    assert first_brief.research_plan_source == "model"
    assert first_brief.research_plan_summary.startswith("按本次需求研究")
    assert first_brief.content_hash == repeated_brief.content_hash
    assert first_queries.content_hash == repeated_queries.content_hash
    assert first_plan.content_hash == repeated_plan.content_hash
    assert second_brief.content_hash != first_brief.content_hash
    assert second_queries.content_hash != first_queries.content_hash
    first_structural = {
        query.domain.value: query.query_text
        for query in first_queries.queries
        if query.query_kind is ResearchQueryKind.STRUCTURAL
    }
    second_structural = {
        query.domain.value: query.query_text
        for query in second_queries.queries
        if query.query_kind is ResearchQueryKind.STRUCTURAL
    }
    assert "建筑 文化" in first_structural["visit"]
    assert "本地文化" in second_structural["visit"]
    assert first_structural != second_structural
    assert (
        "检索词：安静 住宿"
        in first_plan.assignments["accommodation_researcher"].objective
    )
    assert set(first_plan.assignments["accommodation_researcher"].research_query_ids) <= set(
        first_queries.query_index()
    )

    payload = _build_plan_gate_payload(
        SimpleNamespace(
            execution_plan=first_plan.execution_plan,
            agent_assignments={
                key: value.model_dump(mode="json")
                for key, value in first_plan.assignments.items()
            },
            controlled_trip_identity=_identity(),
            intent_spec=first_contract.intent_spec,
            constraint_pack={},
            research_brief=first_brief,
            research_query_plan=first_queries,
            plan_gate_revision_count=0,
        )
    )
    assert "**研究重点**：按本次需求研究" in payload["plan_text"]
    assert "研究重点：「建筑」" in payload["plan_text"]
    assert "计划来源" not in payload["plan_text"]

    async def _dispatch():
        state = TravelAgentState(
            run_id="run_model_plan",
            execution_plan=first_plan.execution_plan,
            current_plan_step=0,
            intent_spec=first_contract.intent_spec,
            intent_spec_revision=first_contract.intent_spec.revision,
            planning_generation=generation,
            research_brief=first_brief,
            research_query_plan=first_queries,
            agent_assignments={
                key: value.model_dump(mode="json")
                for key, value in first_plan.assignments.items()
            },
        )
        dispatched = await dispatcher_node(state)
        routed_state = state.model_copy(update=dispatched)
        routes = route_after_dispatcher(routed_state)
        return dispatched, routes

    dispatched, routes = asyncio.run(_dispatch())
    assert dispatched["next_agent"] == "dispatch_group"
    assert routes == "destination_researcher"
    destination_assignment = first_plan.assignments["destination_researcher"]
    assert destination_assignment.research_query_ids
    assert {
        first_queries.query_index()[query_id].query_text
        for query_id in destination_assignment.research_query_ids
    } >= {"杭州 建筑 文化"}


def test_supplement_replaces_model_research_plan_in_a_new_generation():
    contract, generation = _contract()
    first_contract = contract.model_copy(
        update={
            "research_plan": _model_research_plan(
                ("安静 住宿", "往返 交通", "建筑 文化")
            )
        }
    )
    clause = _clause(4, "不要查酒店", source_kind="run_supplement")
    normalized = RequestContractNormalizationResult(
        clauses=[
            NormalizedClauseDraft(
                clause_id=clause.clause_id,
                disposition=ClauseDisposition.MAPPED_TO_INTENT,
                intents=[
                    _intent(
                        IntentKind.MUST_EXCLUDE,
                        IntentTarget.LODGING,
                        CategoryIntentValue(categories=["酒店"]),
                        "不要查酒店",
                        ["research", "composition"],
                    )
                ],
            )
        ],
        research_plan=ResearchPlanDraft(
            domains=[
                ResearchDomainPlanDraft(
                    domain=ResearchDomain.LONG_DISTANCE_TRANSPORT,
                    focus_atoms=["交通"],
                    search_terms=["往返 交通"],
                ),
                ResearchDomainPlanDraft(
                    domain=ResearchDomain.VISIT,
                    focus_atoms=["建筑", "文化"],
                    search_terms=["建筑 文化"],
                ),
            ],
        ),
    )
    revised, revised_generation = build_request_contract_revision(
        run_id="run_intent_contract",
        identity=_identity(),
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
        previous=first_contract,
        plan_revision=1,
        research_plan=normalized.research_plan,
    )

    assert revised_generation.generation_id != generation.generation_id
    assert revised_generation.plan_revision == 1
    assert revised.research_plan == normalized.research_plan
    brief = build_research_brief(revised, _identity())
    queries = build_research_query_plan(
        intent_spec=revised.intent_spec, brief=brief
    )
    assert brief.research_plan_source == "model"
    assert "跨城交通" in brief.research_plan_summary
    assert all(
        objective.domain is not ResearchDomain.LODGING
        for objective in brief.domain_objectives
    )
    assert all(
        query.domain is not ResearchDomain.LODGING for query in queries.queries
    )
    assert "建筑 文化" in next(
        query.query_text
        for query in queries.queries
        if query.domain is ResearchDomain.VISIT
        and query.query_kind is ResearchQueryKind.STRUCTURAL
    )


def test_incomplete_model_research_plan_falls_back_with_explicit_source():
    contract, _generation = _contract()
    incomplete = ResearchPlanDraft(
        domains=[
            ResearchDomainPlanDraft(
                domain=ResearchDomain.VISIT,
                focus_atoms=["建筑"],
                search_terms=["architecture"],
            )
        ],
    )
    brief = build_research_brief(
        contract.model_copy(update={"research_plan": incomplete}), _identity()
    )

    assert brief.research_plan_source == "deterministic_fallback"
    assert brief.research_plan_summary == ""
    assert all(not objective.search_terms for objective in brief.domain_objectives)
    payload = _build_plan_gate_payload(
        SimpleNamespace(
            execution_plan=[["destination_researcher"]],
            agent_assignments={
                "destination_researcher": {"objective": "查找景点"}
            },
            controlled_trip_identity=_identity(),
            intent_spec=contract.intent_spec,
            constraint_pack={},
            research_brief=brief,
            plan_gate_revision_count=0,
        )
    )
    assert "**生成说明**" in payload["plan_text"]
    assert "模型研究计划" in payload["plan_text"]
    assert "**研究范围与检索词**" not in payload["plan_text"]


def test_multi_day_trip_keeps_default_lodging_research_without_exclusion():
    contract, generation = _contract()

    brief, queries, plan = _research_plan(contract, _identity(), generation)

    assert ResearchDomain.LODGING in {
        objective.domain for objective in brief.domain_objectives
    }
    assert any(
        query.domain is ResearchDomain.LODGING
        and query.query_kind is ResearchQueryKind.STRUCTURAL
        for query in queries.queries
    )
    assert "accommodation_researcher" in plan.assignments


@pytest.mark.parametrize(
    ("stages", "keeps_research"),
    [
        (["research", "composition"], False),
        (["composition", "projection"], True),
    ],
)
def test_domain_wide_lodging_exclusion_controls_default_research(
    stages, keeps_research
):
    contract, generation = _contract_with_extra_intents(
        IntentItem(
            intent_id="intent_no_hotel",
            kind=IntentKind.MUST_EXCLUDE,
            target=IntentTarget.LODGING,
            strength=IntentStrength.HARD,
            priority=90,
            value=CategoryIntentValue(categories=["酒店"]),
            source_kind="current_request",
            source_ref_id="query_main",
            verification_mode=VerificationMode.MIXED,
            impact_stages=stages,
            public_summary="不要查酒店",
        )
    )

    brief, queries, plan = _research_plan(contract, _identity(), generation)

    assert (
        ResearchDomain.LODGING
        in {objective.domain for objective in brief.domain_objectives}
    ) is keeps_research
    assert (
        any(query.domain is ResearchDomain.LODGING for query in queries.queries)
    ) is keeps_research
    assert (
        "accommodation_researcher" in plan.assignments
    ) is keeps_research
    owner = (
        "accommodation_researcher"
        if keeps_research and "research" in stages
        else "itinerary_planner"
    )
    assert "intent_no_hotel" in plan.assignments[owner].must_cover_intent_ids
    if not keeps_research:
        assert "住宿查询" not in " ".join(
            assignment.objective for assignment in plan.assignments.values()
        )
        assert "不要查酒店" in plan.assignments["itinerary_planner"].objective


@pytest.mark.parametrize("category", ["连锁酒店", "杭州西湖国宾馆"])
def test_narrow_lodging_exclusion_keeps_default_research(category):
    contract, generation = _contract_with_extra_intents(
        IntentItem(
            intent_id="intent_no_narrow_lodging",
            kind=IntentKind.MUST_EXCLUDE,
            target=IntentTarget.LODGING,
            strength=IntentStrength.HARD,
            priority=90,
            value=CategoryIntentValue(categories=[category]),
            source_kind="current_request",
            source_ref_id="query_main",
            verification_mode=VerificationMode.MIXED,
            impact_stages=["research", "composition"],
            public_summary=f"不要{category}",
        )
    )

    brief, queries, plan = _research_plan(contract, _identity(), generation)

    lodging = next(
        objective
        for objective in brief.domain_objectives
        if objective.domain is ResearchDomain.LODGING
    )
    assert lodging.excluded_categories == [category]
    assert any(
        query.domain is ResearchDomain.LODGING
        and query.query_kind is ResearchQueryKind.STRUCTURAL
        for query in queries.queries
    )
    assert plan.assignments["accommodation_researcher"].excluded_categories == [
        category
    ]


def test_positive_lodging_requirement_survives_a_domain_wide_exclusion():
    contract, generation = _contract_with_extra_intents(
        IntentItem(
            intent_id="intent_prefer_guesthouse",
            kind=IntentKind.MUST_INCLUDE,
            target=IntentTarget.LODGING,
            strength=IntentStrength.HARD,
            priority=95,
            value=CategoryIntentValue(categories=["民宿"]),
            source_kind="current_request",
            source_ref_id="query_main",
            verification_mode=VerificationMode.MIXED,
            impact_stages=["research", "composition"],
            public_summary="住宿优先安排民宿",
        ),
        IntentItem(
            intent_id="intent_no_hotel",
            kind=IntentKind.MUST_EXCLUDE,
            target=IntentTarget.LODGING,
            strength=IntentStrength.HARD,
            priority=90,
            value=CategoryIntentValue(categories=["酒店"]),
            source_kind="current_request",
            source_ref_id="query_main",
            verification_mode=VerificationMode.MIXED,
            impact_stages=["research", "composition"],
            public_summary="不要查酒店",
        ),
    )

    brief, queries, plan = _research_plan(contract, _identity(), generation)

    lodging = next(
        objective
        for objective in brief.domain_objectives
        if objective.domain is ResearchDomain.LODGING
    )
    assert lodging.excluded_categories == ["酒店"]
    assert "intent_prefer_guesthouse" in lodging.must_cover_intent_ids
    assert plan.assignments["accommodation_researcher"].excluded_categories == [
        "酒店"
    ]
    assert any(
        "民宿" in query.query_text
        for query in queries.queries
        if query.domain is ResearchDomain.LODGING
    )


@pytest.mark.parametrize(
    "stages",
    [["projection"], ["composition", "projection"]],
)
def test_non_research_lodging_requirement_does_not_override_domain_wide_exclusion(
    stages,
):
    contract, generation = _contract_with_extra_intents(
        IntentItem(
            intent_id="intent_existing_lodging_in_report",
            kind=IntentKind.OUTPUT_REQUIREMENT,
            target=IntentTarget.LODGING,
            strength=IntentStrength.HARD,
            priority=90,
            value=OutputRequirementValue(
                required_field="用户提供的已订住宿地址",
                applies_to="trip",
            ),
            source_kind="current_request",
            source_ref_id="query_main",
            verification_mode=VerificationMode.DETERMINISTIC,
            impact_stages=stages,
            public_summary="把用户提供的已订住宿地址列入报告",
        ),
        IntentItem(
            intent_id="intent_no_hotel",
            kind=IntentKind.MUST_EXCLUDE,
            target=IntentTarget.LODGING,
            strength=IntentStrength.HARD,
            priority=90,
            value=CategoryIntentValue(categories=["酒店"]),
            source_kind="current_request",
            source_ref_id="query_main",
            verification_mode=VerificationMode.MIXED,
            impact_stages=["research", "composition"],
            public_summary="不要查酒店",
        ),
    )

    brief, queries, plan = _research_plan(contract, _identity(), generation)

    assert ResearchDomain.LODGING not in {
        objective.domain for objective in brief.domain_objectives
    }
    assert not any(
        query.domain is ResearchDomain.LODGING for query in queries.queries
    )
    assert "accommodation_researcher" not in plan.assignments
    assert any(
        "已订住宿地址" in requirement
        for requirement in brief.delivery_requirements
    )


def test_non_research_lodging_requirement_keeps_the_default_without_exclusion():
    contract, generation = _contract_with_extra_intents(
        IntentItem(
            intent_id="intent_existing_lodging_in_report",
            kind=IntentKind.OUTPUT_REQUIREMENT,
            target=IntentTarget.LODGING,
            strength=IntentStrength.HARD,
            priority=90,
            value=OutputRequirementValue(
                required_field="用户提供的已订住宿地址",
                applies_to="trip",
            ),
            source_kind="current_request",
            source_ref_id="query_main",
            verification_mode=VerificationMode.DETERMINISTIC,
            impact_stages=["projection"],
            public_summary="把用户提供的已订住宿地址列入报告",
        )
    )

    brief, queries, plan = _research_plan(contract, _identity(), generation)

    assert ResearchDomain.LODGING in {
        objective.domain for objective in brief.domain_objectives
    }
    assert any(
        query.domain is ResearchDomain.LODGING for query in queries.queries
    )
    assert "accommodation_researcher" in plan.assignments


@pytest.mark.parametrize("same_city", [True, False])
def test_planner_assigns_authoritative_transport_scopes_for_local_and_intercity_trips(same_city):
    from travel_agent.planning.research.plan import planner_node
    from travel_agent.planning.research.transport.scope import (
        transport_provider_assignments,
    )

    contract, generation = _contract()
    identity = _identity()
    if same_city:
        identity["destinations"] = [identity["origin"]]
    local = contract.intent_spec.active_items[0].model_copy(update={
        "intent_id": "intent_local_transit", "kind": IntentKind.MUST_INCLUDE,
        "target": IntentTarget.LOCAL_TRANSPORT, "value": ScalarIntentValue(value="公共交通"),
        "impact_stages": ["research", "composition"],
    })
    contract = contract.model_copy(update={"intent_spec": contract.intent_spec.model_copy(update={
        "active_items": [*contract.intent_spec.active_items, local],
    })})
    brief = build_research_brief(contract, identity)
    state = TravelAgentState(
        run_id="run_intent_contract",
        controlled_trip_identity=identity,
        request_contract=contract,
        intent_spec=contract.intent_spec,
        intent_spec_revision=contract.intent_spec.revision,
        research_brief=brief,
        planning_generation=generation,
        constraint_pack_revision=contract.constraint_pack_revision,
    )
    result = asyncio.run(planner_node(state))
    assignment = result["agent_assignments"]["transport_researcher"]
    assignments = transport_provider_assignments(assignment, state)
    for update in (
        {"run_id": "run_other"},
        {"constraint_pack_revision": state.constraint_pack_revision + 1},
    ):
        with pytest.raises(ValueError, match="authority mismatch"):
            transport_provider_assignments(assignment, state.model_copy(update=update))
    assert {item.scope.transport_class for item in assignments} == (
        {"public_transit", "flexible"} if same_city
        else {"long_distance", "public_transit", "flexible"}
    )
    legs = [item.scope.route_leg for item in assignments if item.scope.route_leg]
    assert [leg.leg_role for leg in legs] == ([] if same_city else ["outbound", "return"])


@pytest.mark.parametrize(
    ("destination_order", "expected_legs", "expected_day_destinations"),
    [
        (
            ("origin_shenzhen", "destination_beijing"),
            [
                (
                    "inter_destination",
                    "origin_shenzhen",
                    "destination_beijing",
                    "2026-11-01",
                    False,
                ),
                (
                    "return",
                    "destination_beijing",
                    "origin_shenzhen",
                    "2026-11-03",
                    True,
                ),
            ],
            ["origin_shenzhen"] * 3 + ["destination_beijing"] * 3,
        ),
        (
            ("destination_beijing", "origin_shenzhen"),
            [
                (
                    "outbound",
                    "origin_shenzhen",
                    "destination_beijing",
                    "2026-10-29",
                    False,
                ),
                (
                    "inter_destination",
                    "destination_beijing",
                    "origin_shenzhen",
                    "2026-11-01",
                    False,
                ),
            ],
            ["destination_beijing"] * 3 + ["origin_shenzhen"] * 3,
        ),
    ],
)
def test_origin_first_and_origin_last_multi_stop_keep_distinct_transport_legs(
    destination_order, expected_legs, expected_day_destinations
):
    from travel_agent.planning.delivery.minimum_draft import (
        build_minimum_delivery_draft,
    )
    from travel_agent.planning.research.plan import planner_node
    from travel_agent.planning.research.transport.scope import (
        transport_provider_assignments,
    )

    contract, generation = _contract()
    base_identity = _identity()
    shenzhen = {
        **base_identity["origin"],
        "place_id": "origin_shenzhen",
        "name": "深圳",
        "display_name": "深圳",
        "latitude": 22.5431,
        "longitude": 114.0579,
        "admin_path": ["广东", "深圳"],
    }
    beijing = {
        **shenzhen,
        "place_id": "destination_beijing",
        "name": "北京",
        "display_name": "北京",
        "latitude": 39.9042,
        "longitude": 116.4074,
        "admin_path": ["北京"],
    }
    places = {item["place_id"]: item for item in (shenzhen, beijing)}
    identity = {
        **base_identity,
        "origin": shenzhen,
        "destinations": [places[item] for item in destination_order],
        "start_date": "2026-10-29",
        "end_date": "2026-11-03",
    }
    brief = build_research_brief(contract, identity)
    state = TravelAgentState(
        run_id="run_origin_first",
        user_query="需要跨日返程",
        controlled_trip_identity=identity,
        request_contract=contract,
        intent_spec=contract.intent_spec,
        intent_spec_revision=contract.intent_spec.revision,
        research_brief=brief,
        planning_generation=generation,
        constraint_pack_revision=contract.constraint_pack_revision,
    )
    result = asyncio.run(planner_node(state))
    assignment = result["agent_assignments"]["transport_researcher"]
    assignments = transport_provider_assignments(assignment, state)
    legs = [item.scope.route_leg for item in assignments if item.scope.route_leg]
    assert [
        (
            leg.leg_role,
            leg.from_place_id,
            leg.to_place_id,
            leg.service_date.isoformat(),
            leg.cross_day_required,
        )
        for leg in legs
    ] == expected_legs
    assert all(leg.from_place_id != leg.to_place_id for leg in legs)
    assert [
        item.place_id for item in brief.controlled_trip_identity.destinations
    ] == list(destination_order)

    draft = build_minimum_delivery_draft(state)
    assert draft is not None
    assert [
        shell.destination_id for shell in draft.day_shells
    ] == expected_day_destinations
    assert [shell.date.isoformat() for shell in draft.day_shells] == [
        "2026-10-29",
        "2026-10-30",
        "2026-10-31",
        "2026-11-01",
        "2026-11-02",
        "2026-11-03",
    ]


@pytest.mark.parametrize("assignment", [{"provider_evidence_assignments": []}, {}])
def test_transport_rejects_empty_or_missing_same_city_scopes(assignment):
    from travel_agent.planning.research.transport.scope import (
        transport_provider_assignments,
    )

    identity = _identity()
    identity["destinations"] = [identity["origin"]]
    state = TravelAgentState(
        run_id="run_local_resume",
        controlled_trip_identity=identity,
        constraint_pack_revision=2,
    )
    with pytest.raises(ValueError, match="requires Provider evidence scopes"):
        transport_provider_assignments(assignment, state)


def test_same_city_exclusions_do_not_create_hotel_or_intercity_research():
    contract, generation = _contract()
    identity = _identity()
    identity["destinations"] = [identity["origin"]]
    identity["end_date"] = identity["start_date"]
    exclusions = [contract.intent_spec.active_items[0].model_copy(update={
        "intent_id": f"excluded_{target.value}", "kind": IntentKind.MUST_EXCLUDE,
        "target": target, "impact_stages": ["research", "composition"],
    }) for target in (IntentTarget.LODGING, IntentTarget.LONG_DISTANCE_TRANSPORT)]
    contract = contract.model_copy(update={"intent_spec": contract.intent_spec.model_copy(update={
        "active_items": [*contract.intent_spec.active_items, *exclusions],
    })})
    brief = build_research_brief(contract, identity)
    queries = build_research_query_plan(intent_spec=contract.intent_spec, brief=brief)
    plan = build_capability_plan(request_contract=contract, brief=brief,
                                 plan_revision=generation.plan_revision, research_query_plan=queries)
    assert "transport_researcher" not in plan.assignments
    assert "accommodation_researcher" not in plan.assignments
    assert {item.intent_id for item in exclusions} <= set(
        plan.assignments["itinerary_planner"].must_cover_intent_ids)


def test_plan_gate_projects_current_trip_scope_and_same_execution_plan():
    contract, generation = _contract()
    identity = _identity()
    second = identity["destinations"][0].copy()
    second.update({
        "place_id": "destination_suzhou",
        "name": "苏州",
        "display_name": "苏州",
        "latitude": 31.2989,
        "longitude": 120.5853,
        "admin_path": ["江苏", "苏州"],
    })
    identity["destinations"] = [*identity["destinations"], second]
    brief = build_research_brief(contract, identity)
    query_plan = build_research_query_plan(
        intent_spec=contract.intent_spec, brief=brief
    )
    plan = build_capability_plan(
        request_contract=contract,
        brief=brief,
        plan_revision=generation.plan_revision,
        research_query_plan=query_plan,
    )
    spec = contract.intent_spec.model_copy(
        update={
            "unresolved_clauses": [
                UnresolvedClause(
                    clause_id="unresolved_scope",
                    source_ref_id="query_main",
                    source_text="预算是否包含往返交通",
                    reason_code="needs_clarification",
                )
            ]
        }
    )
    payload = _build_plan_gate_payload(
        SimpleNamespace(
            execution_plan=plan.execution_plan,
            agent_assignments={
                key: value.model_dump(mode="json")
                for key, value in plan.assignments.items()
            },
            controlled_trip_identity=identity,
            intent_spec=spec,
            constraint_pack={},
            plan_gate_revision_count=0,
            user_query="预算12000元，按合理默认安排，不再补充。",
        )
    )

    text = payload["plan_text"]
    assert "从上海出发" in text and "杭州 → 苏州" in text
    assert "2026-09-01 至 2026-09-03" in text and "2位成人" in text
    assert "建筑与本地文化" in text and "咖啡" in text
    assert "待核实或需要取舍" in text and "预算是否包含往返交通" in text
    assert "默认安排" in text and "出发地、目的地、日期和同行人数不使用默认值" in text
    assert "query_" not in text and "search_web" not in text
    assert {
        query.destination_id for query in query_plan.queries
    } == {"destination_hangzhou", "destination_suzhou"}
    assert payload["plan"]["steps"] == [
        {
            "step": index,
            "agents": agents,
            "tasks": {
                agent: plan.assignments[agent].objective for agent in agents
            },
        }
        for index, agents in enumerate(plan.execution_plan, start=1)
    ]
    assert len(payload["plan"]["steps"]) == len(plan.execution_plan)


def test_plan_gate_presents_recognized_requirements_without_clarification_controls():
    contract, _generation = _contract()
    hard = contract.intent_spec.active_items[0]
    soft = contract.intent_spec.active_items[1].model_copy(
        update={"intent_id": "intent_soft", "strength": IntentStrength.SOFT}
    )
    intent_spec = contract.intent_spec.model_copy(
        update={
            "active_items": [hard, soft],
            "conflicts": [
                IntentConflict(
                    conflict_id="conflict_test",
                    intent_ids=[hard.intent_id, soft.intent_id],
                    conflict_type="direct_contradiction",
                    blocking=False,
                    user_visible_summary="两项要求需要取舍",
                )
            ],
        }
    )
    payload = _build_plan_gate_payload(
        SimpleNamespace(
            execution_plan=[["destination_researcher"]],
            agent_assignments={
                "destination_researcher": {"objective": "research destinations"}
            },
            plan_gate_revision_count=0,
            constraint_pack={"hard_constraints": []},
            intent_spec=intent_spec,
        )
    )

    recognized = payload["recognized_requirements"]
    assert [item["requirement_id"] for item in recognized["hard"]] == [hard.intent_id]
    assert [item["requirement_id"] for item in recognized["preferences"]] == [
        soft.intent_id
    ]
    assert set(recognized) == {"hard", "preferences"}
    assert "approve" in payload["decision_options"]
    assert "must_obey" not in payload


def _gate_state(**updates):
    state = SimpleNamespace(
        run_id="run_gate_version",
        plan_gate_decision=None,
        execution_plan=[["destination_researcher"]],
        agent_assignments={
            "destination_researcher": {"objective": "查找建筑与本地文化地点"}
        },
        controlled_trip_identity=_identity(),
        intent_spec=None,
        constraint_pack={},
        research_brief=None,
        research_query_plan=None,
        capability_plan=None,
        request_contract=SimpleNamespace(content_hash="a" * 64),
        plan_gate_revision_count=0,
    )
    for key, value in updates.items():
        setattr(state, key, value)
    return state


def test_plan_gate_approval_token_is_stable_and_binds_plan_version():
    state = _gate_state()
    payload = _build_plan_gate_payload(state)
    repeated = _build_plan_gate_payload(state)

    assert payload["approval_token"] == repeated["approval_token"]
    assert payload["approval_token"].startswith("plan_gate.approval.v1:")

    changed_plan = _build_plan_gate_payload(
        _gate_state(
            execution_plan=[["accommodation_researcher"]],
            agent_assignments={
                "accommodation_researcher": {"objective": "查找地铁附近住宿"}
            },
        )
    )
    changed_revision = _build_plan_gate_payload(
        _gate_state(plan_gate_revision_count=1)
    )
    changed_contract = _build_plan_gate_payload(
        _gate_state(request_contract=SimpleNamespace(content_hash="b" * 64))
    )
    changed_run = _build_plan_gate_payload(
        _gate_state(run_id="run_gate_version_other")
    )

    tokens = {
        payload["approval_token"],
        changed_plan["approval_token"],
        changed_revision["approval_token"],
        changed_contract["approval_token"],
        changed_run["approval_token"],
    }
    assert len(tokens) == 5


def test_plan_gate_approval_token_survives_sse_and_recovery_projection():
    from travel_agent.api.presenters.runs import _public_pending_user_choice
    from travel_agent.api.sse_projection import project_sse_payload

    payload = _build_plan_gate_payload(_gate_state())
    token = payload["approval_token"]

    live = project_sse_payload(
        {
            "type": "approval_gate_raised",
            "run_id": "run_gate_version",
            "gate": "plan",
            "payload": payload,
        }
    )
    recovered = _public_pending_user_choice(
        {"type": "approval_gate", "gate": "plan", "payload": payload}
    )

    assert live["payload"]["approval_token"] == token
    assert recovered["payload"]["approval_token"] == token
    assert recovered["payload"]["revision"] == payload["revision"]


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["approve", "edit", "supplement"])
async def test_plan_gate_rejects_stale_token_at_checkpoint_consumption(
    monkeypatch, action
):
    from travel_agent.planning.requirements import approval

    stale_payload = _build_plan_gate_payload(_gate_state())
    current_state = _gate_state(
        execution_plan=[["accommodation_researcher"]],
        agent_assignments={
            "accommodation_researcher": {"objective": "查找地铁附近住宿"}
        },
    )
    current_payload = _build_plan_gate_payload(current_state)
    stale_decision = {
        "action": action,
        "approval_token": stale_payload["approval_token"],
    }
    current_decision = {
        "action": action,
        "approval_token": current_payload["approval_token"],
    }
    if action in {"edit", "supplement"}:
        stale_decision["content"] = "更安静一些"
        current_decision["content"] = "更安静一些"
    decisions = iter([stale_decision, current_decision])
    calls = []

    def choose(payload):
        calls.append(payload)
        return next(decisions)

    monkeypatch.setattr(approval, "interrupt", choose)
    monkeypatch.setattr(
        approval,
        "seal_minimum_delivery_draft",
        lambda _state: {"planning_authorized": True},
    )

    result = await approval.plan_gate_node(
        current_state, {"configurable": {"plan_gate_enabled": True}}
    )

    assert len(calls) == 2
    assert calls[0]["approval_token"] == current_payload["approval_token"]
    assert calls[1]["approval_token"] == current_payload["approval_token"]
    if action == "approve":
        assert result["plan_gate_decision"] == {
            "action": "approve",
            "revision": 0,
        }
        assert result["planning_authorized"] is True
    else:
        assert result["plan_gate_amendment"].content == "更安静一些"
        assert result["plan_gate_revision_count"] == 1


@pytest.mark.asyncio
async def test_plan_gate_cancel_does_not_require_an_approval_token(monkeypatch):
    from travel_agent.planning.requirements import approval
    from travel_agent.runtime.cancellation import RunCancelled

    monkeypatch.setattr(approval, "interrupt", lambda _payload: {"action": "cancel"})

    with pytest.raises(RunCancelled):
        await approval.plan_gate_node(
            _gate_state(), {"configurable": {"plan_gate_enabled": True}}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("revision_count", [0, 1])
@pytest.mark.parametrize("prior_action", [None, "projection_amendment_pending"])
async def test_requirement_classification_does_not_require_an_extra_approval_step(
    monkeypatch, revision_count, prior_action
):
    from travel_agent.planning.requirements import approval
    from travel_agent.planning.requirements.intent_contracts import UnresolvedClause

    contract, _generation = _contract()
    spec = contract.intent_spec.model_copy(
        update={
            "unresolved_clauses": [
                UnresolvedClause(
                    clause_id="unresolved-1",
                    source_ref_id="query_main",
                    source_text="希望更特别一点",
                    reason_code="needs_clarification",
                )
            ],
            "conflicts": [
                IntentConflict(
                    conflict_id="conflict_test",
                    intent_ids=[item.intent_id for item in contract.intent_spec.active_items[:2]],
                    conflict_type="direct_contradiction",
                    blocking=True,
                    user_visible_summary="两项要求需要取舍",
                )
            ],
        }
    )
    state = SimpleNamespace(
        run_id="gate-summary",
        plan_gate_decision={"action": prior_action} if prior_action else None,
        execution_plan=[["destination_researcher"]],
        agent_assignments={},
        plan_gate_revision_count=revision_count,
        constraint_pack={},
        intent_spec=spec,
    )
    calls = []

    def choose(payload):
        calls.append(payload)
        assert len(calls) == 1
        assert "approve" in payload["decision_options"]
        assert set(payload["recognized_requirements"]) == {"hard", "preferences"}
        return {
            "action": "approve",
            "approval_token": payload["approval_token"],
        }

    monkeypatch.setattr(approval, "interrupt", choose)
    monkeypatch.setattr(approval, "seal_minimum_delivery_draft", lambda _state: {"planning_authorized": True})
    result = await approval.plan_gate_node(state, {"configurable": {"plan_gate_enabled": True}})
    # 展示性修改也必须让用户看到新计划后再次确认，不能沿用旧决定静默批准。
    assert len(calls) == 1
    assert result["plan_gate_decision"]["action"] == "approve"
    assert result["planning_authorized"] is True


@pytest.mark.parametrize(("text", "amount"), [("预算5000元", 5000), ("预算最多 12,000 元", 12000), ("总预算约 5,000 元", 5000)])
def test_budget_amount_survives_thousands_separator_and_clause_splitting(text, amount):
    [clause] = split_source_clauses([("query_main", "current_request", text)])
    [budget] = deterministic_budget_constraints(clause.source_text)
    assert budget["params"]["amount"] == amount


@pytest.mark.asyncio
async def test_model_context_classification_does_not_crash_material_requirement():
    clause = _clause(0, "必须住得安静")
    class ContextModel:
        async def ainvoke(self, *_args, **_kwargs):
            return json.dumps({"clauses": [{"clause_id": clause.clause_id, "disposition": "background_context", "reason_code": None, "intents": [], "constraints": []}]})
    normalized = await normalize_clauses(clauses=[clause], controlled_identity=_identity(), llm=ContextModel())
    [draft] = normalized.clauses
    assert draft.disposition is ClauseDisposition.UNRESOLVED
    contract, _generation = build_request_contract_revision(run_id="material-context", identity=_identity(), identity_revision=1, constraint_pack={}, constraint_pack_revision=1, clauses=[clause], normalized=normalized)
    assert contract.has_unresolved_material_clauses


def test_previous_trip_facts_do_not_become_current_requirements():
    from travel_agent.planning.requirements.constraints.sources import constraint_free_text_sources
    state = SimpleNamespace(user_query="这次独自去青岛", session_anchor={}, plan_gate_amendment=None, pending_intent_amendments=[])
    sources = constraint_free_text_sources(state, [{"category": "trip_plan", "content": "上次西安旅行，两位成人"}, {"category": "preference", "content": "喜欢海边散步"}])
    assert [item["text"] for item in sources] == ["这次独自去青岛", "喜欢海边散步"]


def test_full_trip_sentence_does_not_treat_party_size_as_nightly_budget():
    text = (
        "上海到杭州两天一夜行程，2名成人，偏好建筑与本地文化，"
        "必须安排两个景点，总预算人民币3000元以内"
    )

    [budget] = deterministic_budget_constraints(text)
    assert budget["params"] == {
        "amount": 3000.0,
        "currency": "CNY",
        "per": "total",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_text", "expected_terms"),
    [
        ("必须安排西湖、郭庄", ["西湖", "郭庄"]),
        ("请务必参观故宫博物院、天坛公园", ["故宫博物院", "天坛公园"]),
        ("一定要打卡良渚博物院，京杭大运河博物馆", ["良渚博物院", "京杭大运河博物馆"]),
    ],
)
async def test_valid_model_semantics_are_not_overruled_by_fallback_grammar(
    source_text, expected_terms
):
    clause = _clause(0, source_text)

    class _Model:
        async def ainvoke(self, *_args, **_kwargs):
            return json.dumps(
                {
                    "clauses": [
                        {
                            "clause_id": clause.clause_id,
                            "disposition": "mapped_to_intent",
                            "reason_code": None,
                            "intents": [
                                {
                                    "kind": "objective",
                                    "target": "trip",
                                    "strength": "hard",
                                    "priority": 90,
                                    "value": {
                                        "value_type": "scalar",
                                        "value": source_text,
                                    },
                                    "verification_mode": "mixed",
                                    "impact_stages": [
                                        "research",
                                        "composition",
                                        "projection",
                                    ],
                                    "public_summary": source_text,
                                }
                            ],
                            "constraints": [],
                        }
                    ]
                }
            )

    result = await normalize_clauses(
        clauses=[clause], controlled_identity=_identity(), llm=_Model()
    )

    [intent] = result.clauses[0].intents
    # 模型给出的语义原样生效：目标值就是原文，没有被兜底语法切词改写。
    assert intent.kind is IntentKind.OBJECTIVE
    assert intent.target is IntentTarget.TRIP
    assert intent.value.value == source_text
    assert all(term in intent.value.value for term in expected_terms)
    assert intent.public_summary == source_text


@pytest.mark.asyncio
async def test_provider_failure_uses_required_items_grammar_only_as_fallback():
    clause = _clause(0, "必须安排西湖、郭庄")

    class _ProviderFailureModel:
        async def ainvoke(self, *_args, **_kwargs):
            raise OpenAIError("provider returned invalid structured output")

    result = await normalize_clauses(
        clauses=[clause],
        controlled_identity=_identity(),
        llm=_ProviderFailureModel(),
    )

    assert [intent.value.categories for intent in result.clauses[0].intents] == [
        ["西湖"],
        ["郭庄"],
    ]


@pytest.mark.asyncio
async def test_valid_model_intents_are_returned_without_rule_rewriting():
    clause = _clause(0, "必须安排甲景点、乙景点")

    class _Model:
        async def ainvoke(self, *_args, **_kwargs):
            return json.dumps(
                {
                    "clauses": [
                        {
                            "clause_id": clause.clause_id,
                            "disposition": "mapped_to_intent",
                            "reason_code": None,
                            "intents": [
                                {
                                    "kind": "must_include",
                                    "target": "visit",
                                    "strength": "hard",
                                    "priority": 73,
                                    "value": {
                                        "value_type": "category",
                                        "categories": ["甲景点"],
                                    },
                                    "verification_mode": "mixed",
                                    "impact_stages": ["research", "composition"],
                                    "public_summary": "甲景点必须保留",
                                },
                                {
                                    "kind": "must_include",
                                    "target": "visit",
                                    "strength": "hard",
                                    "priority": 74,
                                    "value": {
                                        "value_type": "category",
                                        "categories": ["乙景点"],
                                    },
                                    "verification_mode": "mixed",
                                    "impact_stages": ["research", "composition"],
                                    "public_summary": "乙景点必须保留",
                                },
                            ],
                            "constraints": [],
                        }
                    ]
                }
            )

    result = await normalize_clauses(
        clauses=[clause], controlled_identity=_identity(), llm=_Model()
    )

    assert [intent.priority for intent in result.clauses[0].intents] == [73, 74]
    assert [intent.public_summary for intent in result.clauses[0].intents] == [
        "甲景点必须保留",
        "乙景点必须保留",
    ]
    assert [intent.impact_stages for intent in result.clauses[0].intents] == [
        ["research", "composition"],
        ["research", "composition"],
    ]


@pytest.mark.asyncio
async def test_required_transport_service_gets_the_transport_domain():
    clause = _clause(0, "必须安排去返程高铁")

    class _ProviderFailureModel:
        async def ainvoke(self, *_args, **_kwargs):
            raise OpenAIError("provider truncated structured output")

    result = await normalize_clauses(
        clauses=[clause], controlled_identity=_identity(), llm=_ProviderFailureModel()
    )

    [intent] = result.clauses[0].intents
    assert intent.kind is IntentKind.MUST_INCLUDE
    assert intent.target is IntentTarget.LONG_DISTANCE_TRANSPORT
    assert intent.value.categories == ["去返程高铁"]


@pytest.mark.asyncio
async def test_provider_failure_maps_an_unnumbered_alternative_request():
    clause = _clause(0, "并给出备选方案")

    class _ProviderFailureModel:
        async def ainvoke(self, *_args, **_kwargs):
            raise OpenAIError("provider returned invalid structured output")

    result = await normalize_clauses(
        clauses=[clause],
        controlled_identity=_identity(),
        llm=_ProviderFailureModel(),
    )

    [intent] = result.clauses[0].intents
    assert intent.kind is IntentKind.ALTERNATIVES
    assert intent.target is IntentTarget.DELIVERY
    assert intent.value.count == 2
    assert result.clauses[0].reason_code is None


@pytest.mark.asyncio
async def test_provider_failure_keeps_safe_parts_and_flags_compound_clause():
    query = (
        "规划两天一夜行程，2名成人，偏好建筑与本地文化，"
        "必须安排甲景点、乙景点，总预算人民币3000元以内。"
        "请安排去返程高铁、住宿、每天的具体时间和交通，并给出备选方案。"
    )
    clauses = split_source_clauses([("query_main", "current_request", query)])

    class _ProviderFailureModel:
        async def ainvoke(self, *_args, **_kwargs):
            raise OpenAIError("provider returned invalid structured output")

    result = await normalize_clauses(
        clauses=clauses,
        controlled_identity=_identity(),
        llm=_ProviderFailureModel(),
    )

    material_dispositions = [
        draft.disposition
        for clause, draft in zip(clauses, result.clauses)
        if is_material_clause(clause.source_text)
    ]
    assert material_dispositions.count(ClauseDisposition.UNRESOLVED) == 1
    unresolved = [
        draft
        for draft in result.clauses
        if draft.disposition is ClauseDisposition.UNRESOLVED
    ]
    assert unresolved[0].reason_code == "semantic_normalization_required"
    intents = [intent for draft in result.clauses for intent in draft.intents]
    assert [
        intent.value.categories[0]
        for intent in intents
        if intent.kind is IntentKind.MUST_INCLUDE
    ] == ["甲景点", "乙景点"]
    assert any(intent.kind is IntentKind.ALTERNATIVES for intent in intents)
    [budget] = [
        constraint
        for draft in result.clauses
        for constraint in draft.constraints
        if constraint.category == "budget_cap"
    ]
    assert budget.params.amount == 3000
    assert budget.params.per == "total"


def test_include_exclude_conflict_blocks_the_contract():
    common = {
        "target": IntentTarget.VISIT,
        "strength": IntentStrength.HARD,
        "priority": 90,
        "source_kind": "current_request",
        "source_ref_id": "query_main",
        "verification_mode": VerificationMode.MIXED,
        "impact_stages": ["research"],
    }
    include = IntentItem(
        intent_id="intent_include",
        kind=IntentKind.MUST_INCLUDE,
        value=CategoryIntentValue(categories=["故宫"]),
        public_summary="必须安排故宫",
        **common,
    )
    exclude = IntentItem(
        intent_id="intent_exclude",
        kind=IntentKind.MUST_EXCLUDE,
        value=CategoryIntentValue(categories=["故宫"]),
        public_summary="不要故宫",
        **common,
    )

    conflicts = detect_intent_conflicts([include, exclude])
    assert len(conflicts) == 1
    assert conflicts[0].blocking is True


def test_current_exclusion_supersedes_a_saved_include_preference():
    clauses = [
        _clause(0, "不要故宫"),
        _clause(1, "喜欢安排故宫", "saved_preference"),
    ]
    normalized = RequestContractNormalizationResult(
        clauses=[
            NormalizedClauseDraft(
                clause_id="clause_0",
                disposition=ClauseDisposition.MAPPED_TO_INTENT,
                intents=[
                    _intent(
                        IntentKind.MUST_EXCLUDE,
                        IntentTarget.VISIT,
                        CategoryIntentValue(categories=["故宫"]),
                        "不要故宫",
                        ["research", "composition"],
                    )
                ],
            ),
            NormalizedClauseDraft(
                clause_id="clause_1",
                disposition=ClauseDisposition.MAPPED_TO_INTENT,
                intents=[
                    _intent(
                        IntentKind.MUST_INCLUDE,
                        IntentTarget.VISIT,
                        CategoryIntentValue(categories=["故宫"]),
                        "喜欢安排故宫",
                        ["composition"],
                    )
                ],
            ),
        ]
    )

    contract, _generation = build_request_contract_revision(
        run_id="run_precedence",
        identity=_identity(),
        identity_revision=1,
        constraint_pack={
            "constraints": [],
            "hard_constraints": [],
            "soft_preferences": [],
            "pack_meta": {},
        },
        constraint_pack_revision=1,
        clauses=clauses,
        normalized=normalized,
    )

    assert [item.kind for item in contract.intent_spec.active_items] == [
        IntentKind.MUST_EXCLUDE
    ]
    assert [item.kind for item in contract.intent_spec.superseded_items] == [
        IntentKind.MUST_INCLUDE
    ]
    assert contract.intent_spec.conflicts == []


def test_current_request_supersedes_structurally_identical_saved_intents():
    clauses = [
        _clause(0, "必须安排西湖"),
        _clause(1, "历史偏好要求安排西湖", "saved_preference"),
    ]
    normalized = RequestContractNormalizationResult(
        clauses=[
            NormalizedClauseDraft(
                clause_id=clause.clause_id,
                disposition=ClauseDisposition.MAPPED_TO_INTENT,
                intents=[
                    _intent(
                        IntentKind.MUST_INCLUDE,
                        IntentTarget.VISIT,
                        CategoryIntentValue(categories=["西湖"]),
                        "必须安排西湖",
                        ["research", "composition"],
                    )
                ],
            )
            for clause in clauses
        ]
    )

    contract, _generation = build_request_contract_revision(
        run_id="run_semantic_dedupe",
        identity=_identity(),
        identity_revision=1,
        constraint_pack={
            "constraints": [],
            "hard_constraints": [],
            "soft_preferences": [],
            "pack_meta": {},
        },
        constraint_pack_revision=1,
        clauses=clauses,
        normalized=normalized,
    )

    [active] = contract.intent_spec.active_items
    [superseded] = contract.intent_spec.superseded_items
    assert active.source_kind == "current_request"
    assert superseded.source_kind == "saved_preference"
    assert active.value == superseded.value


def test_latest_packets_rejects_an_obsolete_generation():
    old_packet = ResearchPacket.model_construct(
        generation_id="generation_old",
        worker_kind="destination_researcher",
    )
    current_packet = ResearchPacket.model_construct(
        generation_id="generation_current",
        worker_kind="destination_researcher",
    )

    latest = _latest_packets(
        {
            "destination_researcher@generation_old": old_packet,
            "destination_researcher_r2@generation_current": current_packet,
        },
        generation_id="generation_current",
    )
    assert latest == {"destination_researcher": current_packet}


def test_runtime_supplement_routes_through_contract_normalization():
    amendment = IntentAmendment(
        command_id="command_runtime_1",
        category="must_do",
        content="必须安排一家本地早餐店",
        source_kind="run_supplement",
    )
    update = apply_runtime_amendments(
        TravelAgentState(
            run_id="run_amendment",
            pending_intent_amendments=[amendment],
            intent_amendment_resume_node="dispatcher",
        )
    )

    assert update["intent_amendment_route"] == "request_contract_normalizer"
    assert update["pending_intent_amendments"][0].impact.value == "research_affecting"
    assert update["plan_gate_revision_count"] == 1


def test_identity_amendment_is_rejected_and_resumes_the_interrupted_node():
    amendment = IntentAmendment(
        command_id="command_runtime_identity",
        category="other",
        content="把目的地改成苏州",
        source_kind="run_supplement",
    )
    update = apply_runtime_amendments(
        TravelAgentState(
            run_id="run_amendment",
            pending_intent_amendments=[amendment],
            intent_amendment_resume_node="dispatcher",
        )
    )

    assert update["pending_intent_amendments"] == []
    assert update["intent_amendment_route"] == "dispatcher"
    assert (
        update["rejected_intent_amendments"][0].reason_code
        == "identity_change_requires_new_run"
    )


def test_unsupported_transaction_amendment_is_rejected():
    amendment = IntentAmendment(
        command_id="command_runtime_purchase",
        category="other",
        content="帮我购买机票并直接付款",
        source_kind="run_supplement",
    )
    update = apply_runtime_amendments(
        TravelAgentState(
            run_id="run_amendment",
            pending_intent_amendments=[amendment],
            intent_amendment_resume_node="dispatcher",
        )
    )

    assert update["pending_intent_amendments"] == []
    assert update["intent_amendment_route"] == "dispatcher"
    assert (
        update["rejected_intent_amendments"][0].reason_code == "unsupported_amendment"
    )


def test_research_amendment_is_rejected_after_the_research_window(monkeypatch):
    amendment = IntentAmendment(
        command_id="command_runtime_late_research",
        category="must_do",
        content="必须安排一家本地早餐店",
        source_kind="run_supplement",
    )
    state = TravelAgentState(
        run_id="run_amendment",
        pending_intent_amendments=[amendment],
        intent_amendment_resume_node="itinerary_planner",
    )
    state.run_deadline = object()
    monkeypatch.setattr('travel_agent.planning.requirements.amendments.observe_run_deadline', lambda deadline: (deadline, SimpleNamespace(research_closed=True, composition_closed=False)))

    update = apply_runtime_amendments(state)

    assert update["pending_intent_amendments"] == []
    assert update["intent_amendment_route"] == "itinerary_planner"
    assert (
        update["rejected_intent_amendments"][0].reason_code == "research_window_closed"
    )
    assert update["rejected_intent_amendments"][0].requires_new_run is True


def test_projection_only_revision_preserves_the_research_generation():
    contract, generation = _contract()
    clause = _clause(4, "报告输出要简洁", "plan_gate_amendment")
    normalized = RequestContractNormalizationResult(
        clauses=[
            NormalizedClauseDraft(
                clause_id=clause.clause_id,
                disposition=ClauseDisposition.MAPPED_TO_INTENT,
                intents=[
                    _intent(
                        IntentKind.OUTPUT_REQUIREMENT,
                        IntentTarget.DELIVERY,
                        OutputRequirementValue(
                            required_field="简洁报告",
                            applies_to="delivery",
                        ),
                        "报告输出要简洁",
                        ["projection"],
                    )
                ],
            )
        ]
    )
    revised, revised_generation = build_request_contract_revision(
        run_id="run_intent_contract",
        identity=_identity(),
        identity_revision=1,
        constraint_pack=contract.constraint_pack,
        constraint_pack_revision=1,
        clauses=[clause],
        normalized=normalized,
        previous=contract,
        plan_revision=1,
        preserve_generation_id=True,
    )

    assert revised.generation_id == generation.generation_id
    assert revised.intent_spec.revision == contract.intent_spec.revision + 1
    assert len(revised.clause_ledger) == len(contract.clause_ledger) + 1


def _model_plan_payload_state(contract, brief, *, revision=0):
    return SimpleNamespace(
        run_id="run_model_plan_gate",
        execution_plan=[["destination_researcher"]],
        agent_assignments={
            "destination_researcher": {"objective": "查找建筑与本地文化地点"}
        },
        controlled_trip_identity=_identity(),
        intent_spec=contract.intent_spec,
        constraint_pack=contract.constraint_pack,
        research_brief=brief,
        research_query_plan=None,
        capability_plan=None,
        request_contract=contract,
        plan_gate_revision_count=revision,
    )


def test_model_plan_with_unapproved_search_term_is_rejected_before_execution():
    contract, _generation = _contract()
    identity = dict(_identity())
    identity["party"] = {
        **identity["party"],
        "accessibility_required": True,
    }
    unapproved = _model_research_plan(
        ("东京 夜店 台阶", "往返 交通", "建筑 文化")
    )
    brief = build_research_brief(
        contract.model_copy(update={"research_plan": unapproved}), identity
    )

    assert brief.research_plan_source == "deterministic_fallback"
    queries = build_research_query_plan(
        intent_spec=contract.intent_spec, brief=brief
    )
    executed_text = " ".join(query.query_text for query in queries.queries)
    assert "东京" not in executed_text
    assert "夜店" not in executed_text
    assert "台阶" not in executed_text
    assert all(not objective.search_terms for objective in brief.domain_objectives)

    payload = _build_plan_gate_payload(_model_plan_payload_state(contract, brief))
    assert payload["plan"]["source"] == "deterministic_fallback"
    assert "东京" not in payload["plan_text"]
    assert "夜店" not in payload["plan_text"]
    assert "台阶" not in payload["plan_text"]
    assert "**研究范围与检索词**" not in payload["plan_text"]


def test_model_plan_contradicting_a_hard_exclusion_is_rejected_as_a_whole():
    contract, _generation = _contract()
    # 用户写了「不要连锁咖啡」：即使模型把排除句当成研究重点引用，也整份拒绝。
    plan = _model_research_plan(
        ("安静 住宿", "往返 交通", "建筑 文化"),
        focus_atoms=("住宿", "交通", "不要连锁咖啡"),
    )
    brief = build_research_brief(
        contract.model_copy(update={"research_plan": plan}), _identity()
    )

    assert brief.research_plan_source == "deterministic_fallback"
    assert "连锁咖啡" not in brief.research_plan_summary
    queries = build_research_query_plan(
        intent_spec=contract.intent_spec, brief=brief
    )
    assert all(
        "连锁咖啡" not in query.query_text for query in queries.queries
    )


def test_legacy_free_text_plan_fields_are_never_confirmed_or_executed():
    contract, _generation = _contract()
    # 旧模型/旧 checkpoint 的正文可以反序列化，但不能进入确认正文或检索参数。
    legacy = _model_research_plan(
        ("安静 住宿", "往返 交通", "建筑 文化")
    ).model_copy(
        update={
            "summary": "东京迪士尼、大阪夜生活、五人十二月行程",
        }
    )
    legacy = legacy.model_copy(
        update={
            "domains": [
                row.model_copy(
                    update={"focus": "顺便查东京迪士尼和五人十二月行程"}
                )
                for row in legacy.domains
            ]
        }
    )
    brief = build_research_brief(
        contract.model_copy(update={"research_plan": legacy}), _identity()
    )

    assert brief.research_plan_source == "model"
    payload = _build_plan_gate_payload(_model_plan_payload_state(contract, brief))
    haystack = " ".join(
        [
            payload["plan_text"],
            *[str(task) for step in payload["plan"]["steps"] for task in step["tasks"].values()],
            *[row["focus"] for row in payload["plan"]["research_scope"]],
            *[objective.summary for objective in brief.domain_objectives],
        ]
    )
    for forbidden in ("东京", "大阪", "五人", "十二月", "迪士尼"):
        assert forbidden not in haystack
    queries = build_research_query_plan(
        intent_spec=contract.intent_spec, brief=brief
    )
    executed = " ".join(query.query_text for query in queries.queries)
    for forbidden in ("东京", "大阪", "五人", "十二月", "迪士尼"):
        assert forbidden not in executed


def test_plan_gate_shows_model_search_terms_and_keeps_them_in_sse_projection():
    from travel_agent.api.sse_projection import public_plan_gate_payload

    contract, _generation = _contract()
    plan = _model_research_plan(("安静 住宿", "往返 交通", "建筑 文化"))
    brief = build_research_brief(
        contract.model_copy(update={"research_plan": plan}), _identity()
    )
    payload = _build_plan_gate_payload(_model_plan_payload_state(contract, brief))

    assert payload["plan"]["source"] == "model"
    assert "**研究范围与检索词**" in payload["plan_text"]
    assert "建筑 文化" in payload["plan_text"]
    assert "安静 住宿" in payload["plan_text"]
    projected = public_plan_gate_payload(payload)
    assert projected["plan"]["source"] == "model"
    assert {
        term
        for row in projected["plan"]["research_scope"]
        for term in row["search_terms"]
    } >= {"安静 住宿", "往返 交通", "建筑 文化"}
    assert projected["retry_available"] is True
    assert projected["approval_token"] == payload["approval_token"]


def test_failed_or_unrecorded_plan_keeps_a_real_retry_path_after_the_revision_limit():
    contract, _generation = _contract()
    fallback = build_research_brief(contract, _identity())
    fallback_payload = _build_plan_gate_payload(
        _model_plan_payload_state(contract, fallback, revision=1)
    )
    assert fallback.research_plan_source == "deterministic_fallback"
    assert fallback_payload["retry_available"] is True
    assert "supplement" in fallback_payload["decision_options"]
    assert "可补充调整后重试" in fallback_payload["plan_text"]

    unrecorded = fallback.model_copy(update={"research_plan_source": "unrecorded"})
    unrecorded_payload = _build_plan_gate_payload(
        _model_plan_payload_state(contract, unrecorded, revision=1)
    )
    assert "历史计划" in unrecorded_payload["plan_text"]
    assert "模型研究计划缺失" not in unrecorded_payload["plan_text"]
    assert unrecorded_payload["retry_available"] is True
    assert "supplement" in unrecorded_payload["decision_options"]

    model_plan = _model_research_plan(("安静 住宿", "往返 交通", "建筑 文化"))
    model_brief = build_research_brief(
        contract.model_copy(update={"research_plan": model_plan}), _identity()
    )
    model_payload = _build_plan_gate_payload(
        _model_plan_payload_state(contract, model_brief, revision=1)
    )
    assert model_payload["retry_available"] is False
    assert model_payload["decision_options"] == ["approve", "cancel"]
    assert "修改额度已用完" in model_payload["plan_text"]


@pytest.mark.asyncio
async def test_normalizer_receives_structured_identity_and_existing_constraints(monkeypatch):
    from travel_agent.planning.requirements.constraints.loading import (
        LoadedConstraintSources,
    )
    from travel_agent.planning.requirements.normalization import node as normalization_node

    class _Model:
        capabilities = SimpleNamespace(supports_json_schema=False)

        def __init__(self):
            self.payload = None

        async def ainvoke(self, messages, **_kwargs):
            self.payload = json.loads(messages[-1]["content"])
            return json.dumps(
                {
                    "clauses": [
                        {
                            "clause_id": item["clause_id"],
                            "disposition": "controlled_identity",
                            "reason_code": None,
                            "intents": [],
                            "constraints": [],
                        }
                        for item in self.payload["clauses"]
                    ],
                    "research_plan": None,
                },
                ensure_ascii=False,
            )

    profile = SimpleNamespace(
        preferences=SimpleNamespace(
            dietary_restrictions=["花生过敏"],
            accommodation_type="住宿必须提供电梯",
            travel_styles=[],
            typical_budget_level="",
            pace="",
            preferred_transport=[],
        )
    )

    async def _load(_state):
        return LoadedConstraintSources(
            user_profile=profile,
            manual_memory_facts=[],
            manual_memory_truncated=False,
            memory_facts=[],
            missing_layers=[],
            partial_reasons=[],
        )

    async def _pack(_state, **_kwargs):
        return {
            "constraints": [],
            "hard_constraints": [],
            "soft_preferences": [],
            "pack_meta": {},
        }

    model = _Model()
    monkeypatch.setattr(normalization_node, "load_constraint_sources", _load)
    monkeypatch.setattr(normalization_node, "build_run_constraint_pack", _pack)
    monkeypatch.setattr(normalization_node, "get_model_router", lambda: object())
    monkeypatch.setattr(
        normalization_node, "llm_for_task", lambda *_args, **_kwargs: model
    )

    await normalization_node.request_contract_normalizer_node(
        TravelAgentState(
            run_id="run_structured_input",
            user_query="帮我规划杭州行程",
            controlled_trip_identity=_identity(),
            controlled_trip_identity_revision=1,
        )
    )

    assert model.payload is not None
    assert model.payload["controlled_identity"]["party"]["adults"] == 2
    assert model.payload["controlled_identity"]["style"]["primary"] == "建筑与本地文化"
    assert model.payload["clauses"][0]["source_kind"] == "current_request"
    constraints = model.payload["existing_constraints"]
    assert any("花生过敏" in item["value"] for item in constraints)
    assert any(
        "电梯" in (item.get("public_summary") or item["value"])
        for item in constraints
    )


@pytest.mark.asyncio
async def test_oversized_model_search_term_is_rejected_without_entering_the_contract():
    from pydantic import ValidationError
    from travel_agent.planning.requirements.research_plan_contracts import (
        ResearchDomainPlanDraft,
    )

    with pytest.raises(ValidationError):
        ResearchDomainPlanDraft(
            domain="visit", focus="查找景点", search_terms=[" " * 100003]
        )

    clause = _clause(0, "帮我规划杭州行程")

    class _Model:
        capabilities = SimpleNamespace(supports_json_schema=False)

        async def ainvoke(self, *_args, **_kwargs):
            return json.dumps(
                {
                    "clauses": [
                        {
                            "clause_id": clause.clause_id,
                            "disposition": "mapped_to_intent",
                            "intents": [
                                {
                                    "kind": "objective",
                                    "target": "trip",
                                    "strength": "hard",
                                    "priority": 90,
                                    "value": {
                                        "value_type": "scalar",
                                        "value": "规划杭州可执行行程",
                                    },
                                    "verification_mode": "mixed",
                                    "impact_stages": [
                                        "research",
                                        "composition",
                                        "projection",
                                    ],
                                    "public_summary": "规划杭州可执行行程",
                                }
                            ],
                        }
                    ],
                    "research_plan": {
                        "summary": "查清杭州。",
                        "domains": [
                            {
                                "domain": "visit",
                                "focus": "查找景点。",
                                "search_terms": [" " * 100003],
                            }
                        ],
                    },
                },
                ensure_ascii=False,
            )

    result = await normalize_clauses(
        clauses=[clause], controlled_identity=_identity(), llm=_Model()
    )
    assert result.research_plan is None
    assert result.clauses[0].intents


def test_legacy_brief_without_source_fields_is_unrecorded_not_a_failed_model_call():
    from travel_agent.planning.research.brief_contracts import ResearchBriefV2

    contract, _generation = _contract()
    current = build_research_brief(contract, _identity())
    legacy_data = current.model_dump(mode="json")
    legacy_data.pop("research_plan_source")
    legacy_data.pop("research_plan_summary")
    legacy = ResearchBriefV2.model_validate(legacy_data)

    assert legacy.research_plan_source == "unrecorded"
    payload = _build_plan_gate_payload(
        _model_plan_payload_state(contract, legacy, revision=1)
    )
    assert "历史计划" in payload["plan_text"]
    assert "模型研究计划缺失" not in payload["plan_text"]
