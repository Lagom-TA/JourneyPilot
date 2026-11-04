"""研究角色的并行交接与候选供给。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from types import SimpleNamespace


from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from travel_agent.planning.graph import build_travel_workflow
from travel_agent.planning.research.output.policy import packet_candidate_limit
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.budget import reset_ledgers
from travel_agent.runtime.journal import current_execution_lease
from travel_agent.tools.exposure import ToolExposurePlan
from travel_agent.tools.gateway_contracts import ToolManifest
from travel_agent.tools.registry import ToolRegistry
from tests.fixtures.research_packets import make_packet
from travel_agent.memory.research_context import project_research_context


def place(name, place_id):
    return {"place_id": place_id, "provider": "osm", "kind": "city", "name": name, "display_name": name, "country_code": "CN", "latitude": 30.2, "longitude": 120.1, "admin_path": []}


IDENTITY = {
    "origin": place("杭州", "city_hangzhou"),
    "destinations": [place("杭州", "city_hangzhou")],
    "start_date": "2026-11-05",
    "end_date": "2026-11-06",
    "party": {"adults": 2, "children": 0, "elderly_companions": False, "accessibility_required": False},
    "style": {"primary": "文化", "secondary_interests": [], "source": "current"},
}

# 双城身份：杭州 → 苏州，研究链要同时覆盖两个目的地。
MULTI_CITY_IDENTITY = {
    "origin": place("杭州", "city_hangzhou"),
    "destinations": [place("杭州", "city_hangzhou"), place("苏州", "city_suzhou")],
    "start_date": "2026-11-05",
    "end_date": "2026-11-06",
    "party": {"adults": 2, "children": 0, "elderly_companions": False, "accessibility_required": False},
    "style": {"primary": "文化", "secondary_interests": [], "source": "current"},
}

# 供身份绑定与来源编译使用的真实检索结果（杭州候选体验 01）。
TOOL_PLACE = {
    "place_id": "supply_place_01",
    "name": "杭州候选体验 01",
    "address": "杭州体验路 1 号",
    "provider_place_type": "tourism;attraction",
    "provider_country_code": "CN",
    "latitude": 30.2,
    "longitude": 120.1,
}


def _visit_candidate(index: int, destination_id: str, label: str) -> dict:
    return {
        "candidate_kind": "visit",
        "candidate_id": f"supply_visit_{index:02d}",
        "research_packet_id": "model_packet",
        "destination_id": destination_id,
        "place_id": f"supply_place_{index:02d}",
        "name": f"{label}候选体验 {index:02d}",
        "address": f"{label}体验路 {index:02d} 号",
        "provider_place_type": "tourism;attraction",
        "provider_country_code": "CN",
        "visit_type": "culture",
        "recommended_duration_minutes": 90,
        "estimated_cost_cny": 60,
        "selection_reasons": [f"第 {index:02d} 个体验的区域分布与取舍建议"],
        "tradeoff": "适合慢游",
        "freshness_status": "current",
        "weather_sensitivity": {"exposure": "outdoor", "rain_sensitivity": "low", "heat_sensitivity": "low", "cold_sensitivity": "low", "wind_sensitivity": "low", "requires_clear_visibility": False},
    }


def _transport_candidate(index: int, destination_id: str) -> dict:
    origin = {"name": "杭州东站", "place_id": "place_origin"}
    target = {"name": "市中心", "place_id": "place_target"}
    return {
        "candidate_kind": "transport",
        "candidate_id": f"supply_transit_{index:02d}",
        "research_packet_id": "model_packet",
        "destination_id": destination_id,
        "route_id": f"route_{index:02d}",
        "transport_class": "public_transit",
        "selected_mode": "metro",
        "from_endpoint": origin,
        "to_endpoint": target,
        "duration_minutes": 40,
        "segments": [
            {
                "segment_id": f"segment_{index:02d}",
                "mode": "metro",
                "from_endpoint": origin,
                "to_endpoint": target,
                "duration_minutes": 40,
            }
        ],
        "booking_status": "not_required",
        "selection_reasons": [f"第 {index:02d} 条衔接的时间成本说明"],
        "tradeoff": "地铁直达",
        "freshness_status": "current",
        "weather_sensitivity": {"exposure": "indoor", "rain_sensitivity": "none", "heat_sensitivity": "low", "cold_sensitivity": "low", "wind_sensitivity": "low", "requires_clear_visibility": False},
    }


def _lodging_candidate(index: int, destination_id: str, *, unavailable: bool = False) -> dict:
    candidate_id = "supply_stay_unavailable" if unavailable else f"supply_stay_{index:02d}"
    return {
        "candidate_kind": "lodging",
        "candidate_id": candidate_id,
        "research_packet_id": "model_packet",
        "destination_id": destination_id,
        "place_id": f"stay_place_{index:02d}",
        "property_name": f"湖畔酒店 {index:02d}",
        "address": f"杭州湖畔路 {index:02d} 号",
        "provider_place_type": "hotel",
        "provider_country_code": "CN",
        "check_in_date": "2026-11-05",
        "check_out_date": "2026-11-06",
        "nights": 1,
        "availability_status": "unavailable" if unavailable else "needs_confirmation",
        "selection_reasons": [f"第 {index:02d} 家的位置取舍建议"],
        "tradeoff": "靠近活动区域",
        "freshness_status": "current",
        "weather_sensitivity": {"exposure": "indoor", "rain_sensitivity": "none", "heat_sensitivity": "none", "cold_sensitivity": "none", "wind_sensitivity": "none", "requires_clear_visibility": False},
    }


def _visit_placement(day_id: str, date: str, destination_id: str, candidate_id: str) -> dict:
    return {
        "placement_kind": "visit", "candidate_id": candidate_id,
        "planned_start": f"{date}T10:00:00+08:00", "planned_end": f"{date}T11:30:00+08:00",
        "duration_minutes": 90, "selection_reason": "慢游首选",
    }


class SupplyModel:
    """按角色返回候选并记录调用顺序的离线模型边界替身。"""

    capabilities = SimpleNamespace(supports_json_schema=False)

    def __init__(self, *, supply: dict[str, list[dict]], itinerary: dict, identity: dict, destination_tool_round: bool = False, fail_once: str | None = None):
        self.worker_order: list[str] = []
        self.worker_requests: dict[str, str] = {}
        self.started: set[str] = set()
        self.both_started = asyncio.Event()
        self.composition_request = ""
        self._supply = supply
        self._itinerary = itinerary
        self._identity = identity
        self._destination_tool_round = destination_tool_round
        self.fail_once = fail_once

    async def ainvoke(self, messages, **kwargs):
        system = str(messages[0].get("content", ""))
        if "研究协调员" in system:
            return json.dumps({"summary": "围绕文化与慢节奏安排行程。"}, ensure_ascii=False)
        if "旅行规划师" in system:
            self.composition_request = "\n".join(str(m.get("content", "")) for m in messages)
            return json.dumps(self._itinerary, ensure_ascii=False)
        if "行程组合器" in system:
            # 为每个相邻段补一段合理的步行估算，让物化按真实路线继续。
            described = json.loads(
                str(messages[-1].get("content", "")).split("待补的相邻段：", 1)[1]
            )
            return json.dumps({"connectors": [
                {
                    "gap_id": gap["gap_id"],
                    "mode": "walk",
                    "duration_minutes": 15,
                    "selection_reason": "离线替身：相邻点步行可达",
                }
                for gap in described
            ]}, ensure_ascii=False)
        return json.dumps({"title": "慢游行程", "days": [{"day_id": "day_1", "theme": "慢游"}]}, ensure_ascii=False)

    async def ainvoke_with_tools_events(self, messages, tools):
        system = str(messages[0].get("content", ""))
        if "正式研究前理解这趟旅行" in system:
            yield {"type": "finish", "content": json.dumps({
                "action": "ready", "trip_identity": self._identity,
                "requirements": "喜欢博物馆和街区漫步，不赶路。",
            }, ensure_ascii=False), "tool_calls": []}
            return
        if "旅行规划师" in system:
            self.composition_request = "\n".join(str(m.get("content", "")) for m in messages)
            yield {"type": "finish", "content": json.dumps(self._itinerary, ensure_ascii=False), "tool_calls": []}
            return
        worker = next(
            name
            for name in (
                "destination_researcher",
                "transport_researcher",
                "accommodation_researcher",
            )
            if f"JourneyPilot 的 {name}" in system
        )
        self.worker_order.append(worker)
        self.worker_requests[worker] = "\n".join(str(m.get("content", "")) for m in messages)
        if worker in {"transport_researcher", "accommodation_researcher"}:
            self.started.add(worker)
            if len(self.started) == 2:
                self.both_started.set()
            await asyncio.wait_for(self.both_started.wait(), timeout=3)
        if worker == self.fail_once:
            self.fail_once = None
            yield {"type": "finish", "content": "无效数据", "tool_calls": []}
            return
        if (
            worker == "destination_researcher"
            and self._destination_tool_round
            and not any(message.get("role") == "tool" for message in messages)
        ):
            yield {"type": "finish", "content": "", "tool_calls": [
                {"id": "place-search", "name": "global_place_search", "arguments": {"query": "杭州 候选体验"}}
            ]}
            return
        yield {"type": "finish", "content": json.dumps({"candidates": self._supply[worker], "source_records": [], "fact_assertions": [], "field_provenance": []}, ensure_ascii=False), "tool_calls": []}


class LeaseStore:
    async def get(self, run_id):
        return SimpleNamespace(lease_token="lease", lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10))


async def _run_research(monkeypatch, model: SupplyModel, identity: dict):
    """使用内存存储和模型替身运行规划图。"""
    from travel_agent.planning.research import research_plan_node
    from travel_agent.planning.research.destination import node as destination
    from travel_agent.planning.research.transport import node as transport
    from travel_agent.planning.research.accommodation import node as accommodation
    from travel_agent.planning.itinerary import node as itinerary
    from travel_agent.planning.weather import node as weather
    from travel_agent.planning.weather.context_builder import unavailable_weather_context
    from travel_agent.planning.requirements.understanding import agent as understanding_agent
    from travel_agent.tools import execution, react

    for module in (research_plan_node, destination, transport, accommodation, itinerary, understanding_agent):
        monkeypatch.setattr(module, "get_model_router", lambda: object())
        monkeypatch.setattr(module, "llm_for_task", lambda *args, **kwargs: model)
    registry = ToolRegistry()

    async def search(query):
        return {"success": True, "query": query, "provider": "fixture", "results": [TOOL_PLACE]}

    registry.register("global_place_search", "查询地点", {"type": "object", "properties": {"query": {"type": "string"}}}, search, manifest=ToolManifest(tool_name="global_place_search"))

    async def search_flights(params):
        return {"success": True, "routes": []}

    registry.register("search_flights", "查询航班", {
        "type": "object", "properties": {"params": {"type": "object"}},
    }, search_flights, manifest=ToolManifest(tool_name="search_flights"))
    monkeypatch.setattr(execution, "get_tool_registry", lambda: registry)
    monkeypatch.setattr(react, "get_tool_registry", lambda: registry)
    monkeypatch.setattr(react, "apply_tool_exposure", lambda tools, name: ToolExposurePlan(False, name, tuple(item["schema"] for item in tools), "", 0, 0, len(tools), len(tools)))
    for module in (destination, transport, accommodation, understanding_agent):
        async def available():
            return registry.get_tools_as_schemas()
        monkeypatch.setattr(module, "get_available_tools", available)

    async def baseline():
        return None

    monkeypatch.setattr("travel_agent.planning.execution.ensure_budget_baseline", baseline)
    from travel_agent.runtime.budget import RunBudgetSnapshot

    monkeypatch.setattr(
        "travel_agent.planning.delivery.minimum_draft.build_run_budget_snapshot",
        lambda: RunBudgetSnapshot(enforce_limits=True, max_tool_calls=20),
    )

    class WeatherBuilder:
        async def build(self, *, requests, trip_start_date, trip_end_date, **kwargs):
            return unavailable_weather_context(requests, trip_start_date=trip_start_date, trip_end_date=trip_end_date)

    monkeypatch.setattr(weather, "_configured_builder", lambda config: WeatherBuilder())

    from tests.support.memory_stores import InMemoryDeliveryBundleStore
    from tests.support.memory_stores import InMemoryTripRunStore
    from travel_agent.runtime.run_contracts import TripRunStatus

    bundles, runs = InMemoryDeliveryBundleStore(), InMemoryTripRunStore()
    await runs.create_run(run_id="supply-flow", session_id="supply-flow", user_id="local", mode="deep")
    await runs.transition_status("supply-flow", TripRunStatus.RUNNING)
    graph = build_travel_workflow().compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "supply-flow", "plan_gate_enabled": True, "run_execution_store": LeaseStore(), "delivery_bundle_store": bundles, "trip_run_store": runs}}
    state = TravelAgentState(
        run_id="supply-flow", session_id="supply-flow",
        user_query="喜欢博物馆和街区漫步，不赶路。",
        controlled_trip_identity=identity,
    )
    token = current_execution_lease.set("lease")
    reset_ledgers()
    try:
        first = await graph.ainvoke(state, config)
        gate = first["__interrupt__"][0].value
        result = await graph.ainvoke(
            Command(resume={"action": "approve", "approval_token": gate["approval_token"]}),
            config,
        )
        if "__interrupt__" in result:
            retry_gate = result["__interrupt__"][0].value
            model.retry_gate = retry_gate
            result = await graph.ainvoke(
                Command(resume={"action": "retry", "approval_token": retry_gate["approval_token"]}),
                config,
            )
    finally:
        current_execution_lease.reset(token)
    return gate, result


async def test_workers_share_destination_results_before_composition(monkeypatch):
    supply = {
        "destination_researcher": [
            _visit_candidate(1, "city_hangzhou", "杭州"),
            _visit_candidate(2, "city_hangzhou", "杭州"),
            _visit_candidate(3, "city_suzhou", "苏州"),
            _visit_candidate(4, "city_suzhou", "苏州"),
        ],
        "transport_researcher": [
            _transport_candidate(1, "city_hangzhou"),
            _transport_candidate(2, "city_suzhou"),
        ],
        "accommodation_researcher": [
            _lodging_candidate(1, "city_hangzhou"),
            _lodging_candidate(2, "city_suzhou"),
        ],
    }
    itinerary = {
        "itinerary_id": "offline_itinerary", "title": "双城慢游", "duration_days": 2,
        "days": [
            {"day_id": "day_1", "day": 1, "date": "2026-11-05", "destination_id": "city_hangzhou", "placements": [_visit_placement("day_1", "2026-11-05", "city_hangzhou", "supply_visit_01")]},
            {"day_id": "day_2", "day": 2, "date": "2026-11-06", "destination_id": "city_suzhou", "placements": [_visit_placement("day_2", "2026-11-06", "city_suzhou", "supply_visit_03")]},
        ],
        "lodging_candidate_ids": [],
    }
    model = SupplyModel(supply=supply, itinerary=itinerary, identity=MULTI_CITY_IDENTITY)
    gate, result = await _run_research(monkeypatch, model, MULTI_CITY_IDENTITY)

    assert model.worker_order[0] == "destination_researcher"
    assert set(model.worker_order[1:]) == {"transport_researcher", "accommodation_researcher"}
    transport_request = model.worker_requests["transport_researcher"]
    # 交通读到两个目的地的候选内容与研究建议，而不是只拿名称或 ID。
    assert "杭州候选体验 01" in transport_request
    assert "苏州候选体验 03" in transport_request
    assert "第 01 个体验的区域分布与取舍建议" in transport_request
    accommodation_request = model.worker_requests["accommodation_researcher"]
    # 两支读取同一份目的地成果，不读取对方尚未完成的结果。
    assert "杭州候选体验 01" in accommodation_request
    assert "苏州候选体验 03" in accommodation_request
    assert "第 01 条衔接的时间成本说明" not in accommodation_request

    workspace = result["trip_workspace"]
    # 双城各安排一站，目的地归属与天数一致。
    assert [day.destination_id for day in workspace.itinerary.day_plans] == [
        "city_hangzhou",
        "city_suzhou",
    ]
    assert [stop.place_id for stop in workspace.itinerary.visit_stops] == [
        "supply_place_01",
        "supply_place_03",
    ]
    assert result["recommendation_catalog"].generation_id == result["planning_generation"].generation_id


async def test_failed_worker_waits_and_retries_without_repeating_sibling(monkeypatch):
    supply = {
        "destination_researcher": [_visit_candidate(1, "city_hangzhou", "杭州")],
        "transport_researcher": [_transport_candidate(1, "city_hangzhou")],
        "accommodation_researcher": [_lodging_candidate(1, "city_hangzhou")],
    }
    itinerary = {
        "itinerary_id": "offline_itinerary", "title": "杭州慢游", "duration_days": 2,
        "days": [
            {"day_id": "day_1", "day": 1, "date": "2026-11-05", "destination_id": "city_hangzhou", "placements": [_visit_placement("day_1", "2026-11-05", "city_hangzhou", "supply_visit_01")]},
            {"day_id": "day_2", "day": 2, "date": "2026-11-06", "destination_id": "city_hangzhou", "placements": [_visit_placement("day_2", "2026-11-06", "city_hangzhou", "supply_visit_01")]},
        ], "lodging_candidate_ids": ["supply_stay_01"],
    }
    model = SupplyModel(supply=supply, itinerary=itinerary, identity=IDENTITY, fail_once="transport_researcher")
    _, result = await _run_research(monkeypatch, model, IDENTITY)
    assert model.retry_gate["gate"] == "research"
    assert model.retry_gate["failed_workers"] == ["transport_researcher"]
    assert "重试沿用本次规划的时限设置" in model.retry_gate["message"]
    assert model.worker_order.count("transport_researcher") == 2
    assert model.worker_order.count("accommodation_researcher") == 1
    assert result["agent_status"]["transport_researcher"] == "completed"
    assert {"supply_transit_01", "supply_stay_01"} <= set(result["recommendation_catalog"].candidate_index())


def test_research_retry_deadline_remains_valid_after_waiting():
    from travel_agent.planning.delivery.minimum_draft import build_minimum_delivery_draft, seal_minimum_delivery_draft
    from travel_agent.planning.requirements.generation_contracts import PlanningGeneration
    from travel_agent.planning.research.gate import _renew_deadline
    from travel_agent.runtime.deadlines import RunDeadlineSnapshot

    state = TravelAgentState(run_id="run", controlled_trip_identity=IDENTITY,
        planning_generation=PlanningGeneration(generation_id="generation", revision=1),
        current_requirements="慢游")
    state = state.model_copy(update={"minimum_delivery_draft": build_minimum_delivery_draft(state)})
    state = state.model_copy(update=seal_minimum_delivery_draft(state))
    state = state.model_copy(update={"research_gate_started_at": (datetime.now(timezone.utc) - timedelta(seconds=3)).isoformat()})
    deadline = _renew_deadline(state)
    RunDeadlineSnapshot.model_validate(deadline.model_dump())


async def test_rich_candidate_supply_reaches_composition_and_workspace(monkeypatch):
    # 14/9/10 明显超过旧配额（12/8/8），并包含一个不可用的未入选住宿候选：
    # 它保留在目录里，但不得阻断交付，也不进入可操作选项。
    stays = [_lodging_candidate(index, "city_hangzhou") for index in range(1, 10)]
    stays.append(_lodging_candidate(10, "city_hangzhou", unavailable=True))
    supply = {
        "destination_researcher": [
            _visit_candidate(index, "city_hangzhou", "杭州") for index in range(1, 15)
        ],
        "transport_researcher": [
            _transport_candidate(index, "city_hangzhou") for index in range(1, 10)
        ],
        "accommodation_researcher": stays,
    }
    itinerary = {
        "itinerary_id": "offline_itinerary", "title": "杭州慢游", "duration_days": 2,
        "days": [
            {"day_id": "day_1", "day": 1, "date": "2026-11-05", "destination_id": "city_hangzhou", "placements": [_visit_placement("day_1", "2026-11-05", "city_hangzhou", "supply_visit_01")]},
            {"day_id": "day_2", "day": 2, "date": "2026-11-06", "destination_id": "city_hangzhou", "placements": [_visit_placement("day_2", "2026-11-06", "city_hangzhou", "supply_visit_02")]},
        ],
        "lodging_candidate_ids": ["supply_stay_01"],
    }
    model = SupplyModel(supply=supply, itinerary=itinerary, identity=IDENTITY, destination_tool_round=True)
    gate, result = await _run_research(monkeypatch, model, IDENTITY)

    catalog = result["recommendation_catalog"]
    candidate_ids = set(catalog.candidate_index())
    assert len([c for c in catalog.candidate_index().values() if c.candidate_kind == "visit"]) == 14
    assert len([c for c in catalog.candidate_index().values() if c.candidate_kind == "transport"]) == 9
    assert len([c for c in catalog.candidate_index().values() if c.candidate_kind == "lodging"]) == 10

    # 组合提示词读到全部候选的实际内容、理由与证据摘要，而不是截取后的子集。
    for candidate_id in sorted(candidate_ids):
        if candidate_id.startswith("supply_transit_"):
            continue
        assert candidate_id in model.composition_request
    assert "supply_visit_14" in model.composition_request
    assert "第 14 个体验的区域分布与取舍建议" in model.composition_request
    assert "supply_stay_09" in model.composition_request
    # 真实工具检索绑定的事实与来源随目录进入组合上下文。
    assert '"facts"' in model.composition_request
    assert '"field_path":"address"' in model.composition_request
    assert '"sources"' in model.composition_request
    assert "杭州候选体验 01" in model.composition_request

    workspace = result["trip_workspace"]
    # 体验槽保留同域的全部未入选备选：两天各选 1 个，每槽 13 个选项
    # （已入选的候选不重复出现在别的槽里），两个槽合起来覆盖全部候选。
    visit_slots = [slot for slot in workspace.selection_slots if slot.slot_type == "visit"]
    assert len(visit_slots) == 2
    options = visit_slots[0].options
    assert len(options) == 13
    assert [option.rank for option in options] == list(range(1, 14))
    assert options[0].candidate_id == "supply_visit_01"
    assert {option.candidate_id for slot in visit_slots for option in slot.options} == {
        f"supply_visit_{index:02d}" for index in range(1, 15)
    }

    # 不可用候选保留在目录与提示词中，但只把可执行的候选变成备选。
    lodging_slots = [slot for slot in workspace.selection_slots if slot.slot_type == "lodging"]
    assert lodging_slots, "行程组合应产出住宿选择槽"
    lodging_options = lodging_slots[0].options
    assert "supply_stay_unavailable" not in {option.candidate_id for option in lodging_options}
    assert len(lodging_options) == 9


def test_candidate_limit_scales_with_trip_size_beyond_old_caps():
    long_multicity = {
        "start_date": "2026-11-05",
        "end_date": "2026-11-15",
        "destinations": [{"place_id": "city_a"}, {"place_id": "city_b"}, {"place_id": "city_c"}],
    }
    # 短途保底与旧上限一致，长途多城按规模放宽，且有输出可读性上限。
    short = {"start_date": "2026-11-05", "end_date": "2026-11-05", "destinations": [{"place_id": "city_a"}]}
    assert packet_candidate_limit("destination_researcher", trip_identity=short) == 12
    assert packet_candidate_limit("accommodation_researcher", trip_identity=short) == 8
    assert packet_candidate_limit("transport_researcher", trip_identity=short) == 8
    assert packet_candidate_limit("destination_researcher", trip_identity=long_multicity) == 36
    assert packet_candidate_limit("accommodation_researcher", trip_identity=long_multicity) == 11
    assert (
        packet_candidate_limit(
            "transport_researcher",
            trip_identity=long_multicity,
            required_route_scopes=[object()] * 4,
        )
        == 16
    )
    # 读不到行程身份时按最短旅行处理，不放大也不报错。
    assert packet_candidate_limit("destination_researcher") == 12


def test_upstream_projection_keeps_advice_for_both_parallel_workers():
    destination_packet = make_packet(
        "dest", worker="destination_researcher", entities=(("visit_a", "tokyo"),)
    )
    transport_packet = make_packet(
        "legs", worker="transport_researcher", entities=(("transit_a", "tokyo"),)
    )
    lodging_packet = make_packet(
        "stay", worker="accommodation_researcher", entities=(("lodging_a", "tokyo"),)
    )
    packets = {
        packet.research_packet_id: packet
        for packet in (destination_packet, transport_packet, lodging_packet)
    }
    scope = {
        "run_id": "run_test",
        "generation_id": "generation_test",
        "fact_data_revision": 1,
        "destination_ids": ["tokyo"],
    }

    def visible_kinds(worker_kind: str) -> set[str]:
        view = project_research_context(packets, worker_kind=worker_kind, **scope)
        return {
            candidate["candidate_kind"]
            for coordination in view.coordination
            for candidate in coordination.candidates
        }

    assert visible_kinds("destination_researcher") == set()
    assert visible_kinds("transport_researcher") == {"visit"}
    assert visible_kinds("accommodation_researcher") == {"visit"}

    transport_view = project_research_context(
        packets, worker_kind="transport_researcher", **scope
    )
    candidate = transport_view.coordination[0].candidates[0]
    assert candidate["selection_reasons"] == ["identity verified", "fits visit"]
    assert candidate["tradeoff"] == "fixture"
    assert transport_view.coordination[0].source_references[0]["title"] == "visit_a"
    stale = destination_packet.model_copy(update={"fact_data_revision": 2})
    packets[stale.research_packet_id] = stale
    assert not project_research_context(packets, worker_kind="transport_researcher", **scope).coordination
