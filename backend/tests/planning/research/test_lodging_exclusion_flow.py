"""真实准备到住宿调研分派的离线集成回归。"""

import json
import re
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from tests.fixtures.chat_execution import prepare
from tests.fixtures.chat_execution import resources as resources
from travel_agent.conversation import intake
from travel_agent.conversation.chat.preparation import ImmediateChat, PreparedChat
from travel_agent.planning.delivery.minimum_draft import (
    minimum_delivery_draft_builder_node,
)
from travel_agent.planning.requirements import approval
from travel_agent.planning.requirements.constraints import loading
from travel_agent.planning.requirements.normalization import node as normalization
from travel_agent.planning.research import research_plan_node
from travel_agent.planning.research.accommodation import binding
from travel_agent.planning.research.accommodation.discovery import (
    discover_deterministic_hotels,
)
from travel_agent.planning.research.brief_node import research_brief_builder_node
from travel_agent.planning.research.dispatch import (
    dispatcher_node,
    route_after_dispatcher,
)
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.plan import planner_node
from travel_agent.planning.research.research_plan_node import (
    research_plan_generator_node,
)
from travel_agent.planning.state import TravelAgentState

_BUDGET = re.compile(r"总预算\s*\d+(?:\.\d+)?(?:\s*元)")


def _place(name):
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
    "destinations": [_place("杭州"), _place("苏州")],
    "start_date": "2026-11-05",
    "end_date": "2026-11-08",
    "party": {"adults": 2, "children": 0},
    "style": {
        "primary": "轻松慢游",
        "secondary_interests": ["博物馆"],
        "source": "current",
    },
}


class _Assessment:
    async def ainvoke(self, messages, **kwargs):
        return SimpleNamespace(
            content=json.dumps(
                {
                    "draft": {},
                    "recognized_requirements": ["总预算12000元"],
                    "questions": [
                        {
                            "id": "budget_scope",
                            "question": "预算包含往返交通吗？",
                            "kind": "single",
                            "options": [
                                {"id": "all", "label": "包括"},
                                {"id": "local", "label": "仅当地"},
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )


class _PlanningModel:
    capabilities = SimpleNamespace(supports_json_schema=False)

    async def ainvoke(self, messages, **kwargs):
        payload = json.loads(messages[-1]["content"])
        if "clauses" in payload:
            return json.dumps(
                {
                    "clauses": [
                        self._clause_row(clause) for clause in payload["clauses"]
                    ]
                },
                ensure_ascii=False,
            )
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

    def _clause_row(self, clause):
        text = clause["text"]
        excluded = "不要查酒店" in text or "避开酒店" in text
        projection = "已订住宿地址" in text
        constraints = []
        budget = _BUDGET.search(text)
        if budget is not None:
            amount = float(re.search(r"\d+(?:\.\d+)?", budget.group(0)).group(0))
            constraints.append(
                {
                    "category": "budget_cap",
                    "value": budget.group(0),
                    "params": {
                        "amount": amount,
                        "currency": "CNY",
                        "per": "total",
                    },
                }
            )
        if projection:
            intent = {
                "kind": "attribute_preference",
                "target": "trip",
                "strength": "hard",
                "priority": 90,
                "value": {"value_type": "scalar", "value": text},
                "verification_mode": "deterministic",
                "impact_stages": ["projection"],
                "public_summary": "把用户提供的已订住宿地址列入报告",
            }
        elif excluded:
            intent = {
                "kind": "must_exclude",
                "target": "lodging",
                "strength": "hard",
                "priority": 100,
                "value": {"value_type": "category", "categories": ["酒店"]},
                "verification_mode": "deterministic",
                "impact_stages": ["research", "composition"],
                "public_summary": text[:300],
            }
        else:
            intent = {
                "kind": "attribute_preference",
                "target": "trip",
                "strength": "soft",
                "priority": 50,
                "value": {"value_type": "scalar", "value": text[:500]},
                "verification_mode": "semantic",
                "impact_stages": ["composition"],
                "public_summary": text[:300],
            }
        return {
            "clause_id": clause["clause_id"],
            "disposition": "mapped_to_intent",
            "reason_code": None,
            "intents": [intent],
            "constraints": constraints,
        }


class _Memory:
    async def get_user_profile(self, *args, **kwargs):
        return None

    async def list_manual_facts(self, *args, **kwargs):
        return []

    async def search_facts(self, *args, **kwargs):
        return []


def _route_after_normalization(state: TravelAgentState) -> str:
    if state.request_contract_candidate is not None:
        return "plan_gate"
    return "brief"


def _install_boundaries(monkeypatch, model):
    monkeypatch.setattr(intake, "get_model_router", lambda: object())
    monkeypatch.setattr(intake, "llm_for_task", lambda *args, **kwargs: _Assessment())
    for module in (normalization, loading):
        monkeypatch.setattr(module, "get_model_router", lambda: object())
        monkeypatch.setattr(module, "llm_for_task", lambda *args, **kwargs: model)
    monkeypatch.setattr(loading, "UserProfileMemory", _Memory)
    monkeypatch.setattr(loading, "MemoryStore", _Memory)
    monkeypatch.setattr(research_plan_node, "get_model_router", lambda: object())
    monkeypatch.setattr(
        research_plan_node, "llm_for_task", lambda *args, **kwargs: model
    )


def _graph():
    builder = StateGraph(TravelAgentState)
    nodes = [
        ("request_contract_normalizer", normalization.request_contract_normalizer_node),
        ("research_plan_generator", research_plan_generator_node),
        ("brief", research_brief_builder_node),
        ("draft", minimum_delivery_draft_builder_node),
        ("planner", planner_node),
        ("plan_gate", approval.plan_gate_node),
        ("dispatcher", dispatcher_node),
    ]
    for name, node in nodes:
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


@pytest.mark.parametrize(
    ("initial_text", "projection_only"),
    [
        ("规划旅行，总预算12000元", False),
        (
            "规划旅行，总预算12000元；把我提供的已订住宿地址列入报告",
            True,
        ),
    ],
)
async def test_domain_wide_lodging_exclusion_reaches_plan_and_discovery(
    monkeypatch, resources, initial_text, projection_only
):
    resources.checkpointer = object()
    _install_boundaries(monkeypatch, _PlanningModel())

    body = {
        "messages": [
            {
                "role": "user",
                "content": initial_text,
                "message_id": "offline-initial",
            }
        ],
        "session_id": "offline-lodging-exclusion",
        "route": "trip_planning",
        "controlled_trip_identity": _IDENTITY,
    }
    first = await prepare(body, resources)
    assert isinstance(first, ImmediateChat)
    events = [event async for event in first.events]
    guided = events[0]["guided_intake"]
    guided["answers"] = [
        {
            "question_id": "budget_scope",
            "selected_option_ids": ["sensible_default"],
        }
    ]
    body["messages"][0]["message_id"] = "offline-confirm"
    body["guided_intake"] = guided

    prepared = await prepare(body, resources)
    assert isinstance(prepared, PreparedChat)
    assert "按合理默认安排，不再补充" in prepared.user_message
    try:
        graph = _graph()
        config = {
            "configurable": {
                "thread_id": prepared.trip_run.run_id,
                "plan_gate_enabled": True,
            }
        }
        initial = {
            "run_id": prepared.trip_run.run_id,
            "user_id": "local",
            "session_id": "offline-lodging-exclusion",
            "user_query": prepared.user_message,
            "controlled_trip_identity": _IDENTITY,
        }

        first_plan = await graph.ainvoke(TravelAgentState(**initial), config)
        before_payload = first_plan["__interrupt__"][0].value
        assert before_payload.get("phase") is None
        assert "默认安排" in before_payload["plan_text"]
        assert before_payload["approval_token"].startswith(
            "plan_gate.approval.v1:"
        )

        amended = await graph.ainvoke(
            Command(
                resume={
                    "action": "supplement",
                    "content": "不要查酒店",
                    "approval_token": before_payload["approval_token"],
                }
            ),
            config,
        )
        question = amended["__interrupt__"][0].value
        # 排除项先给简短确认问题；此时还没有计划或研究授权。
        assert question["plan"]["steps"] == []
        assert "不要查酒店" in question["plan_text"]
        assert "approve" not in question["decision_options"]
        assert amended["research_brief"] is None
        if projection_only:
            assert any(
                item.target.value == "trip"
                and item.kind.value == "attribute_preference"
                and item.impact_stages == ["projection"]
                and "已订住宿地址" in item.public_summary
                for item in amended["intent_spec"].active_items
            )

        after = await graph.ainvoke(
            Command(
                resume={
                    "action": "supplement",
                    "content": "是的，要避开酒店",
                    "approval_token": question["approval_token"],
                }
            ),
            config,
        )
        payload = after["__interrupt__"][0].value
        assert payload["plan"]["steps"], (
            "exclusion confirmation must resume planning instead of asking again"
        )
        if projection_only:
            assert any(
                "已订住宿地址" in requirement
                for requirement in after["research_brief"].delivery_requirements
            )
        assert payload["revision"] == 2
        assert payload["approval_token"] != before_payload["approval_token"]
        assert (
            first_plan["planning_generation"].generation_id
            != after["planning_generation"].generation_id
        )
        assert payload["plan"]["steps"] == [
            {
                "step": index,
                "agents": group,
                "tasks": {
                    agent: after["agent_assignments"][agent]["objective"]
                    for agent in group
                },
            }
            for index, group in enumerate(after["execution_plan"], start=1)
        ]
        assert all(
            "accommodation_researcher" not in step["agents"]
            for step in payload["plan"]["steps"]
        )
        assert "住宿查询" not in payload["plan_text"]
        assert "不要查酒店" in payload["plan_text"]
        assert not any(
            query.domain is ResearchDomain.LODGING
            for query in after["research_query_plan"].queries
        )

        approved = await graph.ainvoke(
            Command(
                resume={
                    "action": "approve",
                    "approval_token": payload["approval_token"],
                }
            ),
            config,
        )
        assert approved["planning_generation"] == after["planning_generation"]
        assert approved["minimum_delivery_draft"].planning_authorized
        assert approved["research_operation_approval"] is not None
        assert approved["run_budget"] and approved["run_deadline"]

        state = TravelAgentState.model_validate(approved)
        state.agent_status = {
            agent: "completed" for agent in state.execution_plan[0]
        }
        state = state.model_copy(update=await dispatcher_node(state))
        routes = route_after_dispatcher(state)
        dispatched = (
            [item.node for item in routes]
            if isinstance(routes, list)
            else [routes]
        )
        assert "accommodation_researcher" not in dispatched

        calls = []

        async def execute_tool(name, args, **kwargs):
            calls.append({"name": name, "args": args})
            return {"status": "failed", "error": "offline test"}

        monkeypatch.setattr(binding, "execute_tool", execute_tool)
        assignment = state.agent_assignments.get(
            "accommodation_researcher", {}
        )
        query_ids = set(assignment.get("research_query_ids", []))
        planned = [
            query
            for query in state.research_query_plan.queries
            if query.query_id in query_ids
        ]
        await discover_deterministic_hotels(
            state=state,
            messages=[],
            available_tools=[
                {"schema": {"function": {"name": "maps_text_search"}}}
            ],
            tool_context={},
            authoritative_tool_results=[],
            planned_queries=planned,
            executed_query_ids=[],
        )
        assert planned == []
        assert calls == []
    finally:
        await prepared.lease_keeper.release(reason="offline_test_done")
