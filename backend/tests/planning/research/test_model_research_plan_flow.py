"""自然语言需求、方案确认、研究和交付的离线链路。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from travel_agent.planning.graph import build_travel_workflow
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.budget import RunBudgetSnapshot, reset_ledgers
from travel_agent.runtime.journal import current_execution_lease
from travel_agent.tools.exposure import ToolExposurePlan
from travel_agent.tools.gateway_contracts import ToolManifest
from travel_agent.tools.registry import ToolRegistry


def place(name, place_id):
    return {"place_id": place_id, "provider": "osm", "kind": "city", "name": name, "display_name": name, "country_code": "CN", "latitude": 30.2, "longitude": 120.1, "admin_path": []}


IDENTITY = {
    "origin": place("杭州", "city_hangzhou"),
    "destinations": [place("杭州", "city_hangzhou")],
    "start_date": "2026-11-05", "end_date": "2026-11-05",
    "party": {"adults": 2, "children": 0, "elderly_companions": False, "accessibility_required": False},
    "style": {"primary": "文化", "secondary_interests": [], "source": "current"},
}


class OfflineModel:
    capabilities = SimpleNamespace(supports_json_schema=False)

    def __init__(self):
        self.plan_requests = []
        self.plan_instructions = []
        self.worker_requests = {}
        self.worker_tools = {}
        self.composition_request = ""

    async def ainvoke(self, messages, **kwargs):
        system = str(messages[0].get("content", ""))
        if "研究协调员" in system:
            payload = json.loads(messages[-1]["content"])
            self.plan_requests.append(payload)
            self.plan_instructions.append(system)
            changed = "园林" in payload["整理后的旅行要求"]
            interest = "园林" if changed else "博物馆"
            return json.dumps({"summary": f"围绕{interest}与慢节奏安排杭州，每天最多两个景点。"}, ensure_ascii=False)
        if "旅行规划师" in system:
            self.composition_request = "\n".join(str(message.get("content", "")) for message in messages)
            return json.dumps({
                "itinerary_id": "offline_itinerary", "title": "杭州慢游", "duration_days": 1,
                "days": [{"day_id": "day_1", "day": 1, "date": "2026-11-05", "destination_id": "city_hangzhou", "placements": [{
                    "placement_kind": "visit", "candidate_id": "garden_candidate",
                    "planned_start": "2026-11-05T10:00:00+08:00", "planned_end": "2026-11-05T11:30:00+08:00", "duration_minutes": 90, "selection_reason": "园林慢游",
                }]}], "lodging_candidate_ids": [],
            }, ensure_ascii=False)
        return json.dumps({"title": "杭州园林慢慢游", "days": [{"day_id": "day_1", "theme": "在杭州园林中慢慢游览"}]}, ensure_ascii=False)

    async def ainvoke_with_tools_events(self, messages, tools):
        system = str(messages[0].get("content", ""))
        if "正式研究前理解这趟旅行" in system:
            self.understanding_request = "\n".join(str(message.get("content", "")) for message in messages)
            interest = "园林" if "改成园林" in self.understanding_request else "博物馆"
            requirements = f"喜欢{interest}，不赶路，每天最多两个景点，返程不要跨日，步行少一些，并使用火车。"
            yield {"type": "finish", "content": json.dumps({"action": "ready", "trip_identity": IDENTITY, "requirements": requirements}, ensure_ascii=False), "tool_calls": []}
            return
        if "旅行规划师" in system:
            # 组合在工具循环内运行：替身不调用工具，直接返回行程草稿。
            self.composition_request = "\n".join(str(message.get("content", "")) for message in messages)
            yield {"type": "finish", "content": json.dumps({
                "itinerary_id": "offline_itinerary", "title": "杭州慢游", "duration_days": 1,
                "days": [{"day_id": "day_1", "day": 1, "date": "2026-11-05", "destination_id": "city_hangzhou", "placements": [{
                    "placement_kind": "visit", "candidate_id": "garden_candidate",
                    "planned_start": "2026-11-05T10:00:00+08:00", "planned_end": "2026-11-05T11:30:00+08:00", "duration_minutes": 90, "selection_reason": "园林慢游",
                }]}], "lodging_candidate_ids": [],
            }, ensure_ascii=False), "tool_calls": []}
            return
        worker = next(name for name in ("destination_researcher", "transport_researcher", "accommodation_researcher") if f"JourneyPilot 的 {name}" in system)
        self.worker_requests[worker] = "\n".join(str(message.get("content", "")) for message in messages)
        self.worker_tools[worker] = tools
        if worker == "destination_researcher" and not any(message.get("role") == "tool" for message in messages):
            yield {"type": "finish", "content": "", "tool_calls": [
                {"id": "search", "name": "global_place_search", "arguments": {"query": "杭州园林实际检索"}},
                {"id": "second", "name": "global_place_search", "arguments": {"query": "第二次查询"}},
            ]}
        else:
            candidates = [{
                "candidate_kind": "visit", "candidate_id": "garden_candidate", "research_packet_id": "model_packet",
                "destination_id": "city_hangzhou", "place_id": "garden_place", "name": "杭州花园",
                "address": "杭州花园路1号", "provider_place_type": "tourism;attraction", "provider_country_code": "CN",
                "visit_type": "nature", "recommended_duration_minutes": 90, "selection_reasons": ["园林慢游"],
                "tradeoff": "时间充裕", "freshness_status": "current",
                "weather_sensitivity": {"exposure": "outdoor", "rain_sensitivity": "low", "heat_sensitivity": "low", "cold_sensitivity": "low", "wind_sensitivity": "low", "requires_clear_visibility": False},
            }] if worker == "destination_researcher" else []
            yield {"type": "finish", "content": json.dumps({"candidates": candidates, "source_records": [], "fact_assertions": [], "field_provenance": []}, ensure_ascii=False), "tool_calls": []}


class LeaseStore:
    async def get(self, run_id):
        return SimpleNamespace(lease_token="lease", lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10))


async def test_confirmed_idea_and_travel_understanding_reach_research_and_delivery(monkeypatch):
    from travel_agent.planning.research import research_plan_node
    from travel_agent.planning.research.destination import node as destination
    from travel_agent.planning.research.transport import node as transport
    from travel_agent.planning.research.accommodation import node as accommodation
    from travel_agent.planning.itinerary import node as itinerary
    from travel_agent.planning.weather.context_builder import unavailable_weather_context
    from travel_agent.planning.weather import node as weather
    from travel_agent.tools import execution, react
    from travel_agent.runtime import budget

    model, calls = OfflineModel(), []
    from travel_agent.planning.requirements.understanding import agent as understanding_agent
    for module in (research_plan_node, destination, transport, accommodation, itinerary, understanding_agent):
        monkeypatch.setattr(module, "get_model_router", lambda: object())
        monkeypatch.setattr(module, "llm_for_task", lambda *args, **kwargs: model)
    registry = ToolRegistry()
    async def search(query):
        calls.append(query)
        return {"success": True, "query": query, "provider": "fixture", "results": [{"place_id": "garden_place", "name": "杭州花园", "address": "杭州花园路1号", "provider_place_type": "tourism;attraction", "provider_country_code": "CN", "latitude": 30.2, "longitude": 120.1}]}
    registry.register("global_place_search", "查询地点", {"type": "object", "properties": {"query": {"type": "string"}}}, search, manifest=ToolManifest(tool_name="global_place_search"))
    async def search_flights(params):
        return {"success": True, "routes": []}
    registry.register("search_flights", "查询航班", {
        "type": "object", "properties": {"params": {"type": "object", "properties": {"require_cross_day": {"type": "boolean"}}}},
    }, search_flights, manifest=ToolManifest(tool_name="search_flights"))
    monkeypatch.setattr(execution, "get_tool_registry", lambda: registry)
    monkeypatch.setattr(react, "get_tool_registry", lambda: registry)
    monkeypatch.setattr(react, "apply_tool_exposure", lambda tools, name: ToolExposurePlan(False, name, tuple(item["schema"] for item in tools), "", 0, 0, len(tools), len(tools)))
    for module in (destination, transport, accommodation, understanding_agent):
        async def available():
            schemas = registry.get_tools_as_schemas()
            for tool in schemas:
                if tool["schema"]["function"]["name"] == "search_flights":
                    tool.update(source="mcp", server_name="duffel-flights")
            return schemas
        monkeypatch.setattr(module, "get_available_tools", available)

    async def baseline():
        return None
    monkeypatch.setattr("travel_agent.planning.execution.ensure_budget_baseline", baseline)
    monkeypatch.setattr("travel_agent.planning.delivery.minimum_draft.build_run_budget_snapshot", lambda: RunBudgetSnapshot(enforce_limits=True, max_tool_calls=1))
    weather_calls = []
    class WeatherBuilder:
        async def build(self, *, requests, trip_start_date, trip_end_date, **kwargs):
            weather_calls.append(requests)
            return unavailable_weather_context(requests, trip_start_date=trip_start_date, trip_end_date=trip_end_date)
    monkeypatch.setattr(weather, "_configured_builder", lambda config: WeatherBuilder())

    from tests.support.memory_stores import InMemoryDeliveryBundleStore
    from tests.support.memory_stores import InMemoryTripRunStore
    from travel_agent.runtime.run_contracts import TripRunStatus

    bundles, runs = InMemoryDeliveryBundleStore(), InMemoryTripRunStore()
    await runs.create_run(run_id="offline-flow", session_id="offline-flow", user_id="local", mode="deep")
    await runs.transition_status("offline-flow", TripRunStatus.RUNNING)
    graph = build_travel_workflow().compile(checkpointer=InMemorySaver())
    lease_store = LeaseStore()
    config = {"configurable": {"thread_id": "offline-flow", "plan_gate_enabled": True, "run_execution_store": lease_store, "delivery_bundle_store": bundles, "trip_run_store": runs}}
    state = TravelAgentState(
        run_id="offline-flow", session_id="offline-flow",
        user_query="喜欢博物馆，不赶路，每天最多两个景点，返程不要跨日，并使用火车。",
        understanding_qa=[{"question_id": "pace", "question": "步行节奏？", "answer": "步行少一些"}],
        controlled_trip_identity=IDENTITY,
    )
    token = current_execution_lease.set("lease")
    reset_ledgers()
    try:
        first = await graph.ainvoke(state, config)
        first_gate = first["__interrupt__"][0].value
        assert "博物馆" in first_gate["plan_text"]
        assert not calls and not weather_calls
        second = await graph.ainvoke(Command(resume={"action": "supplement", "content": "改成园林", "approval_token": first_gate["approval_token"]}), config)
        gate = second["__interrupt__"][0].value
        assert "园林" in gate["plan_text"]
        assert gate["approval_token"] != first_gate["approval_token"]
        assert not calls and not weather_calls
        from travel_agent.planning.recovery import with_worker_recovery
        from travel_agent.planning.workflow import TravelPlanningWorkflow

        workflow = object.__new__(TravelPlanningWorkflow)
        workflow._checkpointer = graph.checkpointer
        workflow._graph = graph
        available, checkpoint_id = await workflow.probe_checkpoint("offline-flow")
        assert available and checkpoint_id
        snapshot = await graph.aget_state(config)
        unapproved = TravelAgentState.model_validate(snapshot.values)
        worker = with_worker_recovery("destination_researcher", destination.destination_researcher_node)
        with pytest.raises(PermissionError, match="已确认"):
            await worker(unapproved, config)
        assert not calls and not weather_calls
        stale = await graph.ainvoke(Command(resume={"action": "approve", "approval_token": first_gate["approval_token"]}), config)
        assert stale["__interrupt__"][0].value["approval_token"] == gate["approval_token"]
        assert not calls and not weather_calls
        current_execution_lease.set("stale-lease")
        with pytest.raises(PermissionError, match="租约无效"):
            await graph.ainvoke(Command(resume={"action": "approve", "approval_token": gate["approval_token"]}), config)
        assert not calls
        current_execution_lease.set("lease")
        result = await graph.ainvoke(None, config)
    finally:
        current_execution_lease.reset(token)

    assert len(model.plan_requests) == 2
    assert set(model.plan_requests[-1]) == {"旅行基础信息", "整理后的旅行要求"}
    assert model.plan_requests[-1]["旅行基础信息"]["destinations"] == IDENTITY["destinations"]
    assert model.plan_instructions[0] == model.plan_instructions[1]
    requirements = model.plan_requests[-1]["整理后的旅行要求"]
    assert all(text in requirements for text in ("喜欢园林", "返程不要跨日", "步行少一些", "每天最多两个景点", "使用火车"))
    assert gate["plan_text"] == "围绕园林与慢节奏安排杭州，每天最多两个景点。"
    assert first_gate["plan_text"] == "围绕博物馆与慢节奏安排杭州，每天最多两个景点。"
    workers = (
        "destination_researcher",
        "transport_researcher",
        "accommodation_researcher",
    )
    assert [step["agents"] for step in gate["plan"]["steps"]] == [
        ["destination_researcher"], ["transport_researcher", "accommodation_researcher"],
        ["itinerary_planner"],
    ]
    for worker in workers:
        assert any(step["tasks"].get(worker) == gate["plan_text"] for step in gate["plan"]["steps"])
        assert model.worker_requests[worker].count(gate["plan_text"]) == 1
        assert requirements in model.worker_requests[worker]
    assert calls == ["杭州园林实际检索"]
    assert "每天最多两个景点" in model.worker_requests["destination_researcher"]
    assert "返程不要跨日" in model.worker_requests["transport_researcher"]
    flight_tool = next(tool for tool in model.worker_tools["transport_researcher"] if tool["function"]["name"] == "search_flights")
    flight_parameters = flight_tool["function"]["parameters"]["properties"]["params"]
    assert flight_parameters["properties"]["require_cross_day"] == {"type": "boolean"}
    assert "require_cross_day" not in flight_parameters.get("required", [])
    assert budget.peek_ledger("offline-flow").tool_calls == 1
    assert requirements in model.composition_request
    assert gate["plan"]["steps"][2]["tasks"]["itinerary_planner"] == gate["plan_text"]
    assert model.composition_request.count(gate["plan_text"]) == 1
    assert result["recommendation_catalog"].generation_id == result["planning_generation"].generation_id
    candidate = result["recommendation_catalog"].candidate_index()["garden_candidate"]
    assert candidate.place_id == "garden_place" and candidate.fact_assertion_ids
    assert result["trip_workspace"].requirements == requirements
    assert result["report_projection"] is not None
    assert result["plan_gate_decision"]["action"] == "approve"
    assert result["delivery_persisted"] is True
    persisted = await bundles.get_current("offline-flow")
    assert persisted.workspace.requirements == requirements
    assert (await runs.get_run("offline-flow")).status is TripRunStatus.COMPLETED
