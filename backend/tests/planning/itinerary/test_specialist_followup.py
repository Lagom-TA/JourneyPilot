import json
from types import SimpleNamespace

import pytest

from tests.fixtures.itinerary import itinerary_draft, restore_planning_state, visit_entry
from tests.fixtures.planning_state import make_planning_state
from tests.fixtures.research_catalog import make_catalog, make_visit_packet
from travel_agent.planning.itinerary import composition, node
from travel_agent.planning.itinerary.draft import ItineraryCompositionDraft
from travel_agent.planning.research.transport import followup
from travel_agent.tools.governance import build_tool_execution_envelope


def _state():
    packets = [make_visit_packet(f"visit_{index}", f"地点{index}") for index in (1, 2)]
    placements = []
    for index, (start, end) in enumerate((("08:00", "09:00"), ("09:40", "10:40")), 1):
        entry = visit_entry(start, end)
        entry["candidate_id"] = f"visit_{index}"
        placements.append(entry)
    return restore_planning_state(
        make_planning_state(),
        recommendation_catalog=make_catalog(*packets),
        fact_data_revision=1,
        placement_skeleton=ItineraryCompositionDraft.model_validate(itinerary_draft(placements)),
        execution_plan=[["itinerary_planner"]],
        agent_status={"itinerary_planner": "pending"},
    )


def _route(gap):
    origin = {"name": "地点1", "place_id": gap.from_place_id}
    destination = {"name": "地点2", "place_id": gap.to_place_id}
    return {
        "route_id": "verified-route",
        "transport_class": "public_transit",
        "selected_mode": "metro",
        "from_endpoint": origin,
        "to_endpoint": destination,
        "duration_minutes": 12,
        "segments": [{
            "segment_id": "segment-1", "mode": "metro", "from_endpoint": origin,
            "to_endpoint": destination, "duration_minutes": 12,
        }],
    }


def _envelope(route):
    envelope = build_tool_execution_envelope(
        tool_name="global_route_search", arguments={}, status="success", source="builtin",
        result={"success": True, "provider": "fixture", "routes": [route]},
        audit_id="verified-audit",
    )
    envelope["metadata"]["evidence_allowed"] = True
    return envelope


@pytest.mark.asyncio
async def test_transport_followup_preserves_candidates_and_uses_verified_route(monkeypatch):
    state = _state()
    monkeypatch.setattr(node, "get_model_router", lambda: None)
    monkeypatch.setattr(node, "llm_for_task", lambda *args, **kwargs: object())
    monkeypatch.setattr(followup, "get_model_router", lambda: None)
    monkeypatch.setattr(followup, "llm_for_task", lambda *args, **kwargs: object())
    monkeypatch.setattr(followup, "get_available_tools", lambda: _available())
    monkeypatch.setattr(followup, "filter_tools_for_agent", lambda tools, agent: tools)
    seen = {}

    async def react(**kwargs):
        seen["messages"] = kwargs["messages"]
        gap = json.loads(kwargs["messages"][1]["content"])["接驳缺口"][0]
        from travel_agent.planning.itinerary.connectors import LocalConnectorGap

        route = _route(LocalConnectorGap.model_validate(gap))
        return SimpleNamespace(outcome=followup.ReactOutcome.FINAL_ANSWER, content="已查到地铁路线。", tool_results=[_envelope(route)], error=None)

    monkeypatch.setattr(followup, "streaming_react_loop", react)
    result = await node.itinerary_planner_node(state, {})
    workspace = result["trip_workspace"]
    assert {"visit_1", "visit_2"} <= set(result["recommendation_catalog"].candidate_index())
    assert workspace.itinerary.transport_legs[0].duration_minutes == 12
    assert workspace.itinerary.transport_legs[0].lineage.source_record_ids
    assert workspace.itinerary.unresolved == []
    assert "东京行程需求" in seen["messages"][1]["content"]
    assert "接驳缺口" in seen["messages"][1]["content"]
    from travel_agent.planning.research.assembly import build_candidate_catalog

    rebuilt, _ = build_candidate_catalog(state.model_copy(update={
        "recommendation_catalog": result["recommendation_catalog"],
        "research_packets": {},
    }))
    assert workspace.itinerary.transport_legs[0].lineage.candidate_id in rebuilt.candidate_index()


async def _available():
    return []


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool_status", "expected_status"), [
    ("success", "success"),
    ("failed", "failed"),
])
async def test_followup_distinguishes_empty_result_from_tool_failure(
    monkeypatch, tool_status, expected_status
):
    state = _state()
    monkeypatch.setattr(followup, "get_model_router", lambda: None)
    monkeypatch.setattr(followup, "llm_for_task", lambda *args, **kwargs: object())
    monkeypatch.setattr(followup, "get_available_tools", lambda: _available())
    monkeypatch.setattr(followup, "filter_tools_for_agent", lambda tools, agent: tools)

    async def react(**kwargs):
        envelope = build_tool_execution_envelope(
            tool_name="global_route_search", arguments={}, status=tool_status,
            result={"routes": []} if tool_status == "success" else None,
            error="查询失败" if tool_status == "failed" else None,
        )
        return SimpleNamespace(
            outcome=followup.ReactOutcome.FINAL_ANSWER, content="没有可用路线",
            tool_results=[envelope], error=None,
        )

    monkeypatch.setattr(followup, "streaming_react_loop", react)
    result, catalog = await followup.research_transport_followup(
        state, question="怎么去？", arrangement="上午"
    )

    assert result["status"] == expected_status
    assert result["sanitized_result"]["success"] is (expected_status == "success")
    assert result["sanitized_result"]["routes"] == []
    assert catalog == state.recommendation_catalog


@pytest.mark.asyncio
async def test_missing_route_remains_unresolved(monkeypatch):
    state = _state()
    monkeypatch.setattr(node, "get_model_router", lambda: None)
    monkeypatch.setattr(node, "llm_for_task", lambda *args, **kwargs: object())

    async def no_route(state, **kwargs):
        return {"status": "failed", "error": "查无结果"}, state.recommendation_catalog

    monkeypatch.setattr(node, "research_transport_followup", no_route)
    result = await node.itinerary_planner_node(state, {})
    itinerary = result["trip_workspace"].itinerary
    assert itinerary.transport_legs == []
    assert any("接驳尚未核实" in item for item in itinerary.unresolved)


@pytest.mark.asyncio
async def test_composition_receives_transport_reply_as_tool_message(monkeypatch):
    state = _state()
    captured = []

    async def specialist(current, **kwargs):
        captured.append(kwargs)
        return build_tool_execution_envelope(
            tool_name=followup.FOLLOWUP_TOOL_NAME, arguments={}, source="local",
            result={"success": True, "summary": "该段地铁约12分钟，来源为路线查询。"},
        ), current.recommendation_catalog

    monkeypatch.setattr(composition, "research_transport_followup", specialist)

    class Model:
        async def ainvoke_with_tools_events(self, messages, tools):
            if not any(item.get("role") == "tool" for item in messages):
                yield {"type": "finish", "content": "", "tool_calls": [{
                    "id": "transport-1", "name": followup.FOLLOWUP_TOOL_NAME,
                    "arguments": {"question": "这两处怎么接驳？", "current_arrangement": "上午两处", "destination_id": "destination_tokyo"},
                }]}
            else:
                assert "地铁约12分钟" in messages[-1]["content"]
                yield {"type": "finish", "content": json.dumps(itinerary_draft([visit_entry()]), ensure_ascii=False), "tool_calls": []}

    result = await composition._compose_draft(state, "安排", Model(), available_tools=[], tool_context={})
    assert isinstance(result, ItineraryCompositionDraft)
    assert captured[0]["question"] == "这两处怎么接驳？"
    assert captured[0]["arrangement"] == "上午两处"


@pytest.mark.asyncio
async def test_followup_replay_does_not_repeat_traffic_research(monkeypatch):
    from travel_agent.runtime.journal import WorkerJournal, current_worker_journal
    from tests.support.memory_stores import InMemoryWorkerJournalStore

    state = _state()
    store = InMemoryWorkerJournalStore()
    calls = []
    monkeypatch.setattr(followup, "get_model_router", lambda: None)
    monkeypatch.setattr(followup, "llm_for_task", lambda *args, **kwargs: object())
    monkeypatch.setattr(followup, "get_available_tools", lambda: _available())
    monkeypatch.setattr(followup, "filter_tools_for_agent", lambda tools, agent: tools)

    async def react(**kwargs):
        calls.append(1)
        return SimpleNamespace(outcome=followup.ReactOutcome.FINAL_ANSWER, content="未查到路线", tool_results=[], error=None)

    monkeypatch.setattr(followup, "streaming_react_loop", react)
    token = current_worker_journal.set(WorkerJournal(store, "run", "scope", 0, {}, None))
    try:
        first, _ = await followup.research_transport_followup(state, question="怎么去？", arrangement="上午", request_id="call-1")
    finally:
        current_worker_journal.reset(token)
    version, payload = await store.load("run", "scope")
    token = current_worker_journal.set(WorkerJournal(store, "run", "scope", version, payload, None))
    try:
        second, _ = await followup.research_transport_followup(state, question="怎么去？", arrangement="上午", request_id="call-1")
    finally:
        current_worker_journal.reset(token)
    assert first == second
    assert calls == [1]


def test_composition_recovery_separates_draft_and_materialization():
    from travel_agent.planning.recovery import invocation_scope

    state = _state()
    initial = state.model_copy(update={"placement_skeleton": None})
    assert invocation_scope(initial, "itinerary_planner") != invocation_scope(state, "itinerary_planner")
