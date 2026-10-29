"""真实准备到住宿调研分派的离线集成回归。"""

import json
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
from travel_agent.planning.state import TravelAgentState


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


class _Normalizer:
    async def ainvoke(self, messages, **kwargs):
        rows = []
        for clause in json.loads(messages[-1]["content"])["clauses"]:
            text = clause["text"]
            excluded = "不要查酒店" in text
            projection = "已订住宿地址" in text
            if projection:
                intent = {
                    "kind": "output_requirement",
                    "target": "lodging",
                    "strength": "hard",
                    "priority": 90,
                    "value": {
                        "value_type": "output_requirement",
                        "required_field": "用户提供的已订住宿地址",
                        "applies_to": "trip",
                    },
                    "verification_mode": "deterministic",
                    "impact_stages": ["projection"],
                    "public_summary": "把用户提供的已订住宿地址列入报告",
                }
            else:
                intent = {
                    "kind": (
                        "must_exclude" if excluded else "attribute_preference"
                    ),
                    "target": "lodging" if excluded else "trip",
                    "strength": "hard" if excluded else "soft",
                    "priority": 100 if excluded else 50,
                    "value": (
                        {"value_type": "category", "categories": ["酒店"]}
                        if excluded
                        else {"value_type": "scalar", "value": text[:500]}
                    ),
                    "verification_mode": (
                        "deterministic" if excluded else "semantic"
                    ),
                    "impact_stages": (
                        ["research", "composition"]
                        if excluded
                        else ["composition"]
                    ),
                    "public_summary": text[:300],
                }
            rows.append(
                {
                    "clause_id": clause["clause_id"],
                    "disposition": "mapped_to_intent",
                    "reason_code": None,
                    "intents": [intent],
                    "constraints": [],
                }
            )
        return json.dumps({"clauses": rows}, ensure_ascii=False)


class _Memory:
    async def get_user_profile(self, *args, **kwargs):
        return None

    async def list_manual_facts(self, *args, **kwargs):
        return []

    async def search_facts(self, *args, **kwargs):
        return []


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
    monkeypatch.setattr(intake, "get_model_router", lambda: object())
    monkeypatch.setattr(intake, "llm_for_task", lambda *args, **kwargs: _Assessment())
    for module in (normalization, loading):
        monkeypatch.setattr(module, "get_model_router", lambda: object())
        monkeypatch.setattr(
            module, "llm_for_task", lambda *args, **kwargs: _Normalizer()
        )
    monkeypatch.setattr(loading, "UserProfileMemory", _Memory)
    monkeypatch.setattr(loading, "MemoryStore", _Memory)

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
        builder = StateGraph(TravelAgentState)
        nodes = [
            (
                "request_contract_normalizer",
                normalization.request_contract_normalizer_node,
            ),
            ("brief", research_brief_builder_node),
            ("draft", minimum_delivery_draft_builder_node),
            ("planner", planner_node),
            ("plan_gate", approval.plan_gate_node),
            ("dispatcher", dispatcher_node),
        ]
        for name, node in nodes:
            builder.add_node(name, node)
        for source, target in [
            (START, "request_contract_normalizer"),
            ("request_contract_normalizer", "brief"),
            ("brief", "draft"),
            ("draft", "planner"),
            ("planner", "plan_gate"),
        ]:
            builder.add_edge(source, target)
        builder.add_conditional_edges(
            "plan_gate",
            approval.route_after_plan_gate,
            {
                "request_contract_normalizer": "request_contract_normalizer",
                "dispatcher": "dispatcher",
            },
        )
        builder.add_edge("dispatcher", END)
        graph = builder.compile(checkpointer=InMemorySaver())
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

        before = await graph.ainvoke(TravelAgentState(**initial), config)
        assert "默认安排" in before["__interrupt__"][0].value["plan_text"]

        after = await graph.ainvoke(
            Command(resume={"action": "supplement", "content": "不要查酒店"}),
            config,
        )
        if projection_only:
            assert any(
                item.target.value == "lodging"
                and item.kind.value == "output_requirement"
                and item.impact_stages == ["projection"]
                for item in after["intent_spec"].active_items
            )
            assert any(
                "已订住宿地址" in requirement
                for requirement in after[
                    "research_brief"
                ].delivery_requirements
            )
        payload = after["__interrupt__"][0].value
        assert payload["revision"] == 1
        assert (
            before["planning_generation"].generation_id
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
            Command(resume={"action": "approve"}), config
        )
        assert approved["planning_generation"] == after["planning_generation"]
        assert approved["minimum_delivery_draft"].planning_authorized
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
