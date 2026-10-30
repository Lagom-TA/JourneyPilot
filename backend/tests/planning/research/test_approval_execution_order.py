"""Approval gates actual research, including the weather provider."""

import asyncio
import json
import re
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from travel_agent.integrations.weather import WeatherProviderNotApplicable
from travel_agent.planning.graph import build_travel_workflow
from travel_agent.planning.nodes import (
    NODE_DISPATCHER,
    NODE_WEATHER_CONTEXT_BUILDER,
)
from travel_agent.planning.delivery.minimum_draft import (
    minimum_delivery_draft_builder_node,
)
from travel_agent.planning.execution import with_run_control
from travel_agent.planning.requirements.constraints import loading
from travel_agent.planning.requirements.normalization import node as normalization
from travel_agent.planning.requirements.normalization.clauses import split_source_clauses
from travel_agent.planning.requirements.normalization.contracts import (
    NormalizedClauseDraft,
    RequestContractNormalizationResult,
)
from travel_agent.planning.requirements.request_contracts import (
    ClauseDisposition,
    IntentAmendment,
)
from travel_agent.planning.requirements.revision import build_request_contract_revision
from travel_agent.planning.research import research_plan_node
from travel_agent.planning.research.brief_node import research_brief_builder_node
from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.weather.context_builder import WeatherContextBuilder
from travel_agent.planning.weather.node import (
    destination_geo_resolver_node,
    weather_context_builder_node,
)
from travel_agent.runtime.cancellation import RunCancelled
from travel_agent.storage import cost_ledger_store


def _place(name):
    return {
        "place_id": f"offline:{name}", "provider": "osm", "kind": "city", "name": name,
        "display_name": name, "country_code": "CN", "latitude": 31.2,
        "longitude": 121.4, "admin_path": [],
    }


IDENTITY = {
    "origin": _place("上海"), "destinations": [_place("杭州")],
    "start_date": "2026-11-05", "end_date": "2026-11-07",
    "party": {"adults": 2, "children": 0},
    "style": {"primary": "经典均衡", "secondary_interests": []},
}

_BUDGET = re.compile(r"预算\s*\d+(?:\.\d+)?(?:\s*元)?")


def _budget_constraint(text: str):
    match = _BUDGET.search(text)
    if match is None:
        return None
    raw = match.group(0)
    amount = float(re.search(r"\d+(?:\.\d+)?", raw).group(0))
    return {
        "category": "budget_cap",
        "value": raw,
        "params": {"amount": amount, "currency": "CNY", "per": "total"},
    }


class OfflinePlanningModel:
    """归一化只整理 clauses；计划阶段只从授权候选里选 ID。"""

    capabilities = SimpleNamespace(supports_json_schema=False)

    def __init__(self):
        self.normalization_calls = 0
        self.selection_calls = 0
        self.payloads = []

    async def ainvoke(self, messages, **_kwargs):
        payload = json.loads(messages[-1]["content"])
        if "clauses" in payload:
            self.normalization_calls += 1
            self.payloads.append(payload)
            return json.dumps(
                {"clauses": [self._row(item) for item in payload["clauses"]]},
                ensure_ascii=False,
            )
        self.selection_calls += 1
        domains = {}
        for domain in payload["required_domains"]:
            candidates = [
                item for item in payload["candidates"] if item["domain"] == domain
            ]
            selected = candidates[0]
            domains[domain] = {
                "focus_candidate_ids": [selected["candidate_id"]],
                "search_candidate_ids": [selected["candidate_id"]],
            }
        return json.dumps({"domains": domains}, ensure_ascii=False)

    def _row(self, clause):
        text = str(clause.get("text") or "")
        constraints = []
        budget = _budget_constraint(text)
        if budget is not None:
            constraints.append(budget)
        return {
            "clause_id": clause["clause_id"],
            "disposition": "mapped_to_intent",
            "reason_code": None,
            "constraints": constraints,
            "intents": [{
                "kind": "objective", "target": "trip", "strength": "soft", "priority": 50,
                "value": {"value_type": "scalar", "value": text[:500]},
                "verification_mode": "semantic",
                "impact_stages": ["research", "composition"],
                "public_summary": text[:300],
            }],
        }


class OfflineMemory:
    async def get_user_profile(self, *_args, **_kwargs):
        return None

    async def list_manual_facts(self, *_args, **_kwargs):
        return []

    async def search_facts(self, *_args, **_kwargs):
        return []


class OfflineCostLedger:
    async def run_summary(self, _run_id):
        return {}


class RecordingWeather:
    name = "offline"

    def __init__(self):
        self.requests = []

    async def fetch_weather(self, request):
        self.requests.append(request)
        raise WeatherProviderNotApplicable("offline fixture")


def _install_boundaries(monkeypatch, model=None):
    model = model or OfflinePlanningModel()
    for module in (normalization, loading):
        monkeypatch.setattr(module, "get_model_router", lambda: object())
        monkeypatch.setattr(module, "llm_for_task", lambda *_args, **_kwargs: model)
    monkeypatch.setattr(loading, "UserProfileMemory", OfflineMemory)
    monkeypatch.setattr(loading, "MemoryStore", OfflineMemory)
    monkeypatch.setattr(cost_ledger_store, "get_cost_ledger_store", lambda: OfflineCostLedger())
    monkeypatch.setattr(research_plan_node, "get_model_router", lambda: object())
    monkeypatch.setattr(
        research_plan_node, "llm_for_task", lambda *_args, **_kwargs: model
    )
    return model


def _config(run_id: str, provider: RecordingWeather) -> dict:
    return {"configurable": {
        "thread_id": run_id, "plan_gate_enabled": True,
        "weather_context_builder": WeatherContextBuilder(
            [provider], max_retries_per_provider=0
        ),
    }}


def _state(run_id: str) -> TravelAgentState:
    return TravelAgentState(
        run_id=run_id, user_id="local", session_id=run_id,
        user_query="规划杭州旅行", controlled_trip_identity=IDENTITY,
    )


async def _start(monkeypatch, model=None, *, interrupt_before=None):
    model = _install_boundaries(monkeypatch, model)
    provider = RecordingWeather()
    run_id = "offline-approval-order"
    graph = build_travel_workflow().compile(
        checkpointer=InMemorySaver(),
        interrupt_before=interrupt_before or [NODE_DISPATCHER],
    )
    config = _config(run_id, provider)
    result = await graph.ainvoke(_state(run_id), config)
    return graph, config, provider, result["__interrupt__"][0].value, model


async def _open_plan(monkeypatch, model=None, *, interrupt_before=None):
    graph, config, provider, payload, model = await _start(
        monkeypatch, model, interrupt_before=interrupt_before
    )
    assert payload.get("phase") is None
    return graph, config, provider, payload


async def test_weather_provider_waits_until_current_plan_is_approved(monkeypatch):
    graph, config, provider, payload, _model = await _start(monkeypatch)
    assert payload.get("phase") is None
    assert payload["gate"] == "plan"
    assert provider.requests == []

    result = await graph.ainvoke(
        Command(resume={"action": "approve", "approval_token": "stale"}), config
    )
    assert result["__interrupt__"][0].value["gate"] == "plan"
    assert provider.requests == []
    await graph.ainvoke(
        Command(
            resume={
                "action": "approve",
                "approval_token": payload["approval_token"],
            }
        ),
        config,
    )
    snapshot = await graph.aget_state(config)
    assert [request.destination_id for request in provider.requests] == ["offline:杭州"]
    assert snapshot.values["minimum_delivery_draft"].planning_authorized
    assert snapshot.values["run_budget"] and snapshot.values["run_deadline"]
    assert snapshot.next == (NODE_DISPATCHER,)


@pytest.mark.parametrize("disposition", ["unresolved", "unsupported"])
async def test_unresolved_material_is_clarified_before_any_plan_or_provider(
    monkeypatch, disposition
):
    class Model(OfflinePlanningModel):
        async def ainvoke(self, messages, **kwargs):
            payload = json.loads(messages[-1]["content"])
            if "clauses" in payload and not any(
                row["source_kind"] == "plan_gate_amendment"
                for row in payload["clauses"]
            ):
                return json.dumps({
                    "clauses": [{
                        "clause_id": row["clause_id"], "disposition": disposition,
                        "reason_code": "mobility_needs_clarification",
                        "intents": [], "constraints": [],
                    } for row in payload["clauses"]],
                }, ensure_ascii=False)
            return await super().ainvoke(messages, **kwargs)

    graph, config, provider, clarification, _model = await _start(monkeypatch, Model())
    assert clarification["plan"]["steps"] == []
    assert "需要先补充" in clarification["plan_text"]
    assert "approve" not in clarification["decision_options"]
    assert "supplement" in clarification["decision_options"]
    assert provider.requests == []
    snapshot = await graph.aget_state(config)
    assert snapshot.values.get("research_brief") is None
    assert snapshot.values.get("research_query_plan") is None

    blocked = await graph.ainvoke(Command(resume={
        "action": "approve", "approval_token": clarification["approval_token"],
    }), config)
    assert "approve" not in blocked["__interrupt__"][0].value["decision_options"]
    assert provider.requests == []

    clarified = await graph.ainvoke(Command(resume={
        "action": "supplement", "content": "长辈需要无障碍交通",
        "approval_token": clarification["approval_token"],
    }), config)
    plan = clarified["__interrupt__"][0].value
    assert plan["plan"]["steps"]
    assert "approve" in plan["decision_options"]
    assert provider.requests == []
    await graph.ainvoke(
        Command(
            resume={
                "action": "approve",
                "approval_token": plan["approval_token"],
            }
        ),
        config,
    )
    assert len(provider.requests) == 1


async def test_edited_plan_is_represented_before_weather_runs(monkeypatch):
    graph, config, provider, payload = await _open_plan(monkeypatch)
    amended = await graph.ainvoke(Command(resume={
        "action": "supplement", "content": "希望交通方便",
        "approval_token": payload["approval_token"],
    }), config)
    updated = amended["__interrupt__"][0].value
    assert updated.get("phase") is None
    assert updated["gate"] == "plan"
    assert updated["approval_token"] != payload["approval_token"]
    assert provider.requests == []
    await graph.ainvoke(
        Command(
            resume={
                "action": "approve",
                "approval_token": updated["approval_token"],
            }
        ),
        config,
    )
    assert len(provider.requests) == 1


async def test_amendment_clarification_reanalyzes_original_until_resolved(monkeypatch):
    class Model(OfflinePlanningModel):
        async def ainvoke(self, messages, **kwargs):
            payload = json.loads(messages[-1]["content"])
            response = json.loads(await super().ainvoke(messages, **kwargs))
            if "clauses" in payload:
                answer_count = sum(
                    row["text"] == "包含往返交通" for row in payload["clauses"]
                )
                for row, draft in zip(payload["clauses"], response["clauses"]):
                    if (
                        row["text"] == "预算5000但往返交通是否包含待确定"
                        and answer_count < 1
                    ):
                        draft.update(
                            disposition="unresolved",
                            reason_code="budget_scope",
                            intents=[],
                        )
            return json.dumps(response, ensure_ascii=False)

    model = Model()
    graph, config, provider, plan = await _open_plan(monkeypatch, model)
    failed = await graph.ainvoke(Command(resume={
        "action": "supplement", "content": "预算5000但往返交通是否包含待确定",
        "approval_token": plan["approval_token"],
    }), config)
    first = failed["__interrupt__"][0].value
    assert first["plan"]["steps"] == []
    assert "预算5000" in first["plan_text"]
    again = await graph.ainvoke(Command(resume={
        "action": "supplement", "content": "包含往返交通",
        "approval_token": first["approval_token"],
    }), config)
    final = again["__interrupt__"][0].value
    assert final.get("phase") is None
    assert final["plan"]["steps"] and "approve" in final["decision_options"]
    assert any(
        "预算5000" in row["text"] for row in model.payloads[-1]["clauses"]
    )
    assert provider.requests == []


async def test_weather_skips_provider_after_research_window_closed(monkeypatch):
    graph, config, provider, payload = await _open_plan(
        monkeypatch,
        interrupt_before=[NODE_WEATHER_CONTEXT_BUILDER, NODE_DISPATCHER],
    )
    await graph.ainvoke(
        Command(
            resume={
                "action": "approve",
                "approval_token": payload["approval_token"],
            }
        ),
        config,
    )
    assert provider.requests == []
    snapshot = await graph.aget_state(config)
    state = TravelAgentState.model_validate(snapshot.values)
    expired = state.run_deadline.model_copy(update={
        "checkpointed_elapsed_seconds": float(
            state.run_deadline.delivery_deadline_seconds + 1
        ),
    })
    state = state.model_copy(update={"run_deadline": expired})
    update = await with_run_control(
        NODE_WEATHER_CONTEXT_BUILDER, weather_context_builder_node
    )(state, config)
    assert provider.requests == []
    assert update["weather_context"].coverage[0].status == "unavailable"


async def test_resumed_expired_weather_checkpoint_does_not_call_provider(monkeypatch):
    graph, config, provider, payload = await _open_plan(
        monkeypatch, interrupt_before=[NODE_WEATHER_CONTEXT_BUILDER, NODE_DISPATCHER],
    )
    await graph.ainvoke(
        Command(
            resume={
                "action": "approve",
                "approval_token": payload["approval_token"],
            }
        ),
        config,
    )
    before = await graph.aget_state(config)
    assert before.next == (NODE_WEATHER_CONTEXT_BUILDER,)
    assert provider.requests == []
    deadline = before.values["run_deadline"]
    expired = deadline.model_copy(update={
        "checkpointed_elapsed_seconds": float(
            deadline.delivery_deadline_seconds + 1
        ),
    })
    await graph.aupdate_state(config, {"run_deadline": expired})
    await graph.ainvoke(None, config)
    after = await graph.aget_state(config)
    assert provider.requests == []
    assert after.values["weather_context"].coverage[0].status == "unavailable"
    assert after.next == (NODE_DISPATCHER,)


async def test_weather_provider_is_cancelled_at_end_of_research_window(monkeypatch):
    graph, config, _provider, payload = await _open_plan(
        monkeypatch,
        interrupt_before=[NODE_WEATHER_CONTEXT_BUILDER, NODE_DISPATCHER],
    )
    await graph.ainvoke(
        Command(
            resume={
                "action": "approve",
                "approval_token": payload["approval_token"],
            }
        ),
        config,
    )
    snapshot = await graph.aget_state(config)
    state = TravelAgentState.model_validate(snapshot.values)
    deadline = state.run_deadline.model_copy(update={
        "checkpointed_elapsed_seconds": float(state.run_deadline.closeout_seconds) - 0.15,
    })
    state = state.model_copy(update={"run_deadline": deadline})

    class SlowWeather:
        name = "offline-slow"
        cancelled = False
        calls = 0

        async def fetch_weather(self, _request):
            self.calls += 1
            try:
                await asyncio.sleep(5)
            finally:
                self.cancelled = True

    provider = SlowWeather()
    config["configurable"]["weather_context_builder"] = WeatherContextBuilder(
        [provider], max_retries_per_provider=0
    )
    update = await with_run_control(
        NODE_WEATHER_CONTEXT_BUILDER, weather_context_builder_node
    )(state, config)
    assert provider.calls == 1 and provider.cancelled
    assert update["weather_context"].coverage[0].status == "unavailable"


async def test_legacy_checkpoint_at_preapproval_weather_returns_to_plan_without_calls(
    monkeypatch,
):
    model = _install_boundaries(monkeypatch)
    provider = RecordingWeather()
    run_id = "legacy-before-weather"
    config = _config(run_id, provider)
    saver = InMemorySaver()
    initial = _state(run_id)

    normalized = await normalization.request_contract_normalizer_node(initial)
    candidate = normalized["request_contract_candidate"]
    state = initial.model_copy(update={
        **normalized,
        "request_contract": candidate,
        "request_contract_candidate": None,
    })
    state = state.model_copy(update=await research_brief_builder_node(state))
    state = state.model_copy(update=await minimum_delivery_draft_builder_node(state))
    geo = destination_geo_resolver_node(state)
    seed = {
        "request_contract": candidate,
        "request_contract_candidate": None,
        "intent_spec": candidate.intent_spec,
        "intent_spec_revision": candidate.intent_spec.revision,
        "constraint_pack": normalized["constraint_pack"],
        "constraint_pack_revision": normalized["constraint_pack_revision"],
        "planning_generation": normalized["planning_generation"],
        "research_brief": state.research_brief,
        "minimum_delivery_draft": state.minimum_delivery_draft,
        "destination_geo": geo["destination_geo"],
    }

    class LegacySeed:
        async def __call__(self, _state):
            return seed

    old = StateGraph(TravelAgentState)
    old.add_node("legacy_seed", LegacySeed())
    old.add_node(NODE_WEATHER_CONTEXT_BUILDER, weather_context_builder_node)
    old.add_edge(START, "legacy_seed")
    old.add_edge("legacy_seed", NODE_WEATHER_CONTEXT_BUILDER)
    old.add_edge(NODE_WEATHER_CONTEXT_BUILDER, END)
    old_graph = old.compile(
        checkpointer=saver, interrupt_before=[NODE_WEATHER_CONTEXT_BUILDER]
    )
    await old_graph.ainvoke(initial, config)
    assert (await old_graph.aget_state(config)).next == (
        NODE_WEATHER_CONTEXT_BUILDER,
    )
    assert provider.requests == []
    assert model.normalization_calls == 1

    new_graph = build_travel_workflow().compile(
        checkpointer=saver, interrupt_before=[NODE_DISPATCHER]
    )
    result = await new_graph.ainvoke(None, config)
    failure = result["__interrupt__"][0].value
    # 旧 checkpoint 有合同但没有研究计划：不自动重生成，先给显式 retry。
    assert failure["plan"]["steps"] == []
    assert "retry" in failure["decision_options"]
    assert provider.requests == []

    retried = await new_graph.ainvoke(
        Command(
            resume={
                "action": "retry",
                "approval_token": failure["approval_token"],
            }
        ),
        config,
    )
    payload = retried["__interrupt__"][0].value
    assert payload["gate"] == "plan"
    assert payload["plan"]["steps"]
    assert model.normalization_calls == 1
    assert model.selection_calls == 1
    assert provider.requests == []
    await new_graph.ainvoke(
        Command(
            resume={
                "action": "approve",
                "approval_token": payload["approval_token"],
            }
        ),
        config,
    )
    assert len(provider.requests) == 1


async def test_legacy_unresolved_amendment_is_reanalyzed_with_new_answer(monkeypatch):
    class Model(OfflinePlanningModel):
        def __init__(self):
            super().__init__()
            self.rows = []

        async def ainvoke(self, messages, **kwargs):
            self.rows = json.loads(messages[-1]["content"])["clauses"]
            return await super().ainvoke(messages, **kwargs)

    model = Model()
    _install_boundaries(monkeypatch, model)
    old_clauses = split_source_clauses(
        [("plan_gate_legacy_1", "plan_gate_amendment", "长辈行动限制待明确")]
    )
    previous, generation = build_request_contract_revision(
        run_id="legacy-unresolved", identity=IDENTITY, identity_revision=1,
        constraint_pack={}, constraint_pack_revision=1, clauses=old_clauses,
        normalized=RequestContractNormalizationResult(clauses=[NormalizedClauseDraft(
            clause_id=old_clauses[0].clause_id,
            disposition=ClauseDisposition.UNRESOLVED,
            reason_code="normalization_failed",
        )]),
    )
    state = TravelAgentState(
        run_id="legacy-unresolved", user_id="local", user_query="规划杭州旅行",
        controlled_trip_identity=IDENTITY, controlled_trip_identity_revision=1,
        request_contract=previous, intent_spec=previous.intent_spec,
        intent_spec_revision=1,
        constraint_pack={}, constraint_pack_revision=1, planning_generation=generation,
        plan_gate_amendment=IntentAmendment(
            command_id="clarification_legacy_2", category="supplement",
            content="长辈需要无障碍交通", source_kind="plan_gate_amendment",
        ),
    )
    result = await normalization.request_contract_normalizer_node(state)
    contract = result["request_contract_candidate"]
    assert old_clauses[0].clause_id in {row["clause_id"] for row in model.rows}
    assert not contract.has_unresolved_material_clauses
    recovered = [
        item for item in [
            *contract.intent_spec.active_items,
            *contract.intent_spec.superseded_items,
        ]
        if item.source_ref_id == "plan_gate_legacy_1"
    ]
    assert recovered and recovered[0].source_text == "长辈行动限制待明确"
    assert recovered[0].source_span_start is None and recovered[0].source_span_end is None


async def test_legacy_replayed_amendment_keeps_all_prior_constraints(monkeypatch):
    class Model(OfflinePlanningModel):
        async def ainvoke(self, messages, **kwargs):
            payload = json.loads(messages[-1]["content"])
            response = json.loads(await super().ainvoke(messages, **kwargs))
            clarified = any(
                "包含往返交通" in item["text"] and "待确定" not in item["text"]
                for item in payload["clauses"]
            )
            for source, draft in zip(payload["clauses"], response["clauses"]):
                if source["text"] == "总预算5000元":
                    draft.update(
                        disposition="mapped_to_constraint", intents=[],
                        constraints=[{
                            "category": "budget_cap",
                            "value": "总预算5000元",
                            "params": {
                                "amount": 5000, "currency": "CNY", "per": "total",
                            },
                        }],
                    )
                elif source["text"] == "但是否包含往返交通待确定":
                    if clarified:
                        draft.update(
                            disposition="non_actionable", intents=[], reason_code=None
                        )
                    else:
                        draft.update(
                            disposition="unresolved", intents=[], reason_code="budget_scope"
                        )
            return json.dumps(response, ensure_ascii=False)

    _install_boundaries(monkeypatch, Model())
    state = TravelAgentState(
        run_id="legacy-budget", user_id="local", user_query="规划杭州旅行",
        controlled_trip_identity=IDENTITY,
        plan_gate_amendment=IntentAmendment(
            command_id="plan_gate_legacy_budget", category="supplement",
            content="总预算5000元，但是否包含往返交通待确定",
            source_kind="plan_gate_amendment",
        ),
    )
    prior = await normalization.request_contract_normalizer_node(state)
    assert any(
        c.get("category") == "budget_cap"
        for c in prior["constraint_pack"]["constraints"]
    )
    assert prior["request_contract_candidate"].has_unresolved_material_clauses
    # Simulate an old checkpoint, which has the ledger but not the retained amendment field.
    previous = state.model_copy(update={
        **prior, "unresolved_intent_amendments": [],
        "plan_gate_amendment": IntentAmendment(
            command_id="clarification_legacy_budget", category="supplement",
            content="包含往返交通", source_kind="plan_gate_amendment",
        ),
    })
    after = await normalization.request_contract_normalizer_node(previous)
    budgets = [
        c for c in after["constraint_pack"]["constraints"]
        if c.get("category") == "budget_cap"
    ]
    assert any(c.get("params", {}).get("amount") == 5000 for c in budgets)
    next_state = previous.model_copy(update={
        **after,
        "plan_gate_amendment": IntentAmendment(
            command_id="clarification_legacy_next", category="supplement",
            content="希望交通方便", source_kind="plan_gate_amendment",
        ),
    })
    later = await normalization.request_contract_normalizer_node(next_state)
    later_budgets = [
        c for c in later["constraint_pack"]["constraints"]
        if c.get("category") == "budget_cap"
    ]
    assert any(c.get("params", {}).get("amount") == 5000 for c in later_budgets)


async def test_replaying_old_sources_never_overwrites_newer_budget(monkeypatch):
    class Model(OfflinePlanningModel):
        async def ainvoke(self, messages, **kwargs):
            payload = json.loads(messages[-1]["content"])
            response = json.loads(await super().ainvoke(messages, **kwargs))
            for source, draft in zip(payload["clauses"], response["clauses"]):
                if "预算5000元" in source["text"] or "预算8000元" in source["text"]:
                    amount = 5000 if "5000" in source["text"] else 8000
                    draft.update(
                        disposition="mapped_to_constraint", intents=[],
                        constraints=[{
                            "category": "budget_cap",
                            "value": f"总预算{amount}元",
                            "params": {
                                "amount": amount, "currency": "CNY", "per": "total",
                            },
                        }],
                    )
            return json.dumps(response, ensure_ascii=False)

    _install_boundaries(monkeypatch, Model())
    state = TravelAgentState(
        run_id="budget-order", user_id="local", user_query="规划杭州旅行",
        controlled_trip_identity=IDENTITY,
    )
    observed = []
    for index, content in enumerate(["总预算5000元", "总预算8000元", "报告简洁"], start=1):
        state = state.model_copy(update={"plan_gate_amendment": IntentAmendment(
            command_id=f"plan_gate_budget_{index}", category="supplement", content=content,
            source_kind="plan_gate_amendment",
        )})
        update = await normalization.request_contract_normalizer_node(state)
        active = [
            c for c in update["constraint_pack"]["constraints"]
            if c.get("category") == "budget_cap" and c.get("status") == "active"
        ]
        observed.append(active[0]["params"]["amount"])
        state = state.model_copy(update=update)
    assert observed == [5000, 8000, 8000]


async def test_user_budget_amendment_supersedes_original_query_and_stays_latest(monkeypatch):
    class Model(OfflinePlanningModel):
        async def ainvoke(self, messages, **kwargs):
            payload = json.loads(messages[-1]["content"])
            response = json.loads(await super().ainvoke(messages, **kwargs))
            for source, draft in zip(payload["clauses"], response["clauses"]):
                if "预算5000元" in source["text"] or "预算8000元" in source["text"]:
                    amount = 5000 if "5000" in source["text"] else 8000
                    draft.update(
                        disposition="mapped_to_constraint", intents=[],
                        constraints=[{
                            "category": "budget_cap",
                            "value": f"总预算{amount}元",
                            "params": {
                                "amount": amount, "currency": "CNY", "per": "total",
                            },
                        }],
                    )
            return json.dumps(response, ensure_ascii=False)

    _install_boundaries(monkeypatch, Model())
    state = TravelAgentState(
        run_id="budget-main-order", user_id="local", user_query="总预算5000元",
        controlled_trip_identity=IDENTITY,
    )
    first = await normalization.request_contract_normalizer_node(state)
    state = state.model_copy(update={
        **first, "plan_gate_amendment": IntentAmendment(
            command_id="plan_gate_budget_change", category="supplement",
            content="总预算8000元", source_kind="plan_gate_amendment",
        ),
    })
    second = await normalization.request_contract_normalizer_node(state)
    state = state.model_copy(update={
        **second, "plan_gate_amendment": IntentAmendment(
            command_id="plan_gate_budget_display", category="supplement",
            content="报告简洁", source_kind="plan_gate_amendment",
        ),
    })
    third = await normalization.request_contract_normalizer_node(state)
    for update in (second, third):
        active = [
            c for c in update["constraint_pack"]["constraints"]
            if c.get("category") == "budget_cap" and c.get("status") == "active"
        ]
        assert len(active) == 1 and active[0]["params"]["amount"] == 8000


async def test_later_normalization_cannot_silently_drop_existing_health_constraint(monkeypatch):
    class Model(OfflinePlanningModel):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def ainvoke(self, messages, **kwargs):
            self.calls += 1
            payload = json.loads(messages[-1]["content"])
            response = json.loads(await super().ainvoke(messages, **kwargs))
            if self.calls == 1:
                for source, draft in zip(payload["clauses"], response["clauses"]):
                    if source["text"] == "同行人需要轮椅":
                        draft.update(
                            disposition="mapped_to_constraint", intents=[],
                            constraints=[{
                                "category": "health_condition",
                                "value": "同行人需要轮椅",
                                "params": {},
                            }],
                        )
            return json.dumps(response, ensure_ascii=False)

    _install_boundaries(monkeypatch, Model())
    initial = TravelAgentState(
        run_id="preserve-wheelchair", user_id="local", user_query="规划杭州旅行",
        controlled_trip_identity=IDENTITY,
        plan_gate_amendment=IntentAmendment(
            command_id="plan_gate_wheelchair", category="supplement",
            content="同行人需要轮椅", source_kind="plan_gate_amendment",
        ),
    )
    first = await normalization.request_contract_normalizer_node(initial)
    assert any(
        c.get("category") == "health_condition"
        for c in first["constraint_pack"]["constraints"]
    )
    after_answer = initial.model_copy(update={
        **first,
        "plan_gate_amendment": IntentAmendment(
            command_id="plan_gate_other", category="supplement",
            content="希望交通方便", source_kind="plan_gate_amendment",
        ),
    })
    second = await normalization.request_contract_normalizer_node(after_answer)
    assert any(
        c.get("category") == "health_condition"
        and "轮椅" in c.get("value", "")
        and c.get("status") == "active"
        for c in second["constraint_pack"]["constraints"]
    )


async def test_cancelled_plan_never_calls_weather_provider(monkeypatch):
    graph, config, provider, _payload = await _open_plan(monkeypatch)
    assert provider.requests == []
    with pytest.raises(RunCancelled):
        await graph.ainvoke(Command(resume={"action": "cancel"}), config)
    assert provider.requests == []
