"""组合补查与反馈返研的行为场景。

真实图 + 离线模型替身：组合在工具循环内自主补查并吸收结果安排时间；
严重不可用的研究成果经「组合反馈 → 指定 Worker 重做 → 新成果 → 继续组合」，
被替代的旧候选退出目录，其他 Worker 的成果保留。
"""

from __future__ import annotations

import json

import pytest
from types import SimpleNamespace

from tests.fixtures.research_packets import make_packet
from tests.fixtures.research_catalog import make_catalog
from tests.planning.research.test_worker_supply import (
    IDENTITY,
    LeaseStore,
    _lodging_candidate,
    _transport_candidate,
    _visit_candidate,
)
from travel_agent.memory.research_context import project_research_context
from travel_agent.planning.research.assembly import build_candidate_catalog
from travel_agent.planning.research.feedback import (
    RESEARCH_REDO_ROUNDS_CAP,
    parse_research_redo_request,
)
from travel_agent.planning.research.progress import worker_result
from travel_agent.planning.state import TravelAgentState
from travel_agent.tools.exposure import ToolExposurePlan
from travel_agent.tools.gateway_contracts import ToolManifest
from travel_agent.tools.registry import ToolRegistry


def _redo_candidate(index: int, destination_id: str) -> dict:
    candidate = _visit_candidate(index, destination_id, "杭州")
    return {
        **candidate,
        "candidate_id": f"redo_visit_{index:02d}",
        "place_id": f"redo_place_{index:02d}",
        "name": f"返研候选 {index:02d}",
    }


class FeedbackModel:
    """按角色返回候选、草稿或返研请求的离线模型边界替身。

    组合在工具循环内运行：`旅行规划师` 分支可以先发起工具调用
    （补查路线/地点），再依据工具结果输出草稿或返研请求。
    """

    capabilities = SimpleNamespace(supports_json_schema=False)

    def __init__(
        self,
        *,
        identity: dict,
        supply: dict[str, list[dict]],
        redo_supply: list[dict],
        itinerary: dict,
        redo_request: dict | None = None,
        route_query: bool = False,
    ):
        self.worker_order: list[str] = []
        self.worker_requests: dict[str, str] = {}
        self.composition_request = ""
        self.composition_transcripts: list[str] = []
        self._identity = identity
        self._supply = supply
        self._redo_supply = redo_supply
        self._itinerary = itinerary
        self._redo_request = redo_request
        self._route_query = route_query
        self.composition_calls = 0
        self._emitted_redo = False

    async def ainvoke(self, messages, **kwargs):
        system = str(messages[0].get("content", ""))
        if "研究协调员" in system:
            return json.dumps({
                "summary": "围绕文化与慢节奏安排行程。",
                "destination_task": "调查适合慢游的体验与餐饮。",
                "transport_task": "查询景点之间的衔接与时间成本。",
                "accommodation_task": "研究靠近活动区域的住宿选择。",
                "itinerary_task": "把体验安排进不赶路的行程。",
            }, ensure_ascii=False)
        if "行程组合器" in system:
            described = json.loads(
                str(messages[-1].get("content", "")).split("待补的相邻段：", 1)[1]
            )
            return json.dumps({"connectors": [
                {"gap_id": gap["gap_id"], "mode": "walk", "duration_minutes": 15, "selection_reason": "离线替身"}
                for gap in described
            ]}, ensure_ascii=False)
        return json.dumps({"title": "慢游行程", "days": [{"day_id": "day_1", "theme": "慢游"}]}, ensure_ascii=False)

    async def astream_with_tools(self, messages, tools):
        system = str(messages[0].get("content", ""))
        if "需求理解者" in system:
            yield {"type": "finish", "content": json.dumps({"action": "ready", "trip_identity": self._identity}, ensure_ascii=False), "tool_calls": []}
            return
        if "旅行规划师" in system:
            self.composition_calls += 1
            self.composition_request = "\n".join(str(m.get("content", "")) for m in messages)
            self.composition_transcripts.append(self.composition_request)
            if self._route_query and not any(m.get("role") == "tool" for m in messages):
                yield {"type": "finish", "content": "", "tool_calls": [
                    {"id": "route-check", "name": "global_route_search",
                     "arguments": {"from": "supply_place_01", "to": "stay_place_01"}},
                ]}
                return
            if self._route_query:
                tool_message = next(m for m in messages if m.get("role") == "tool")
                payload = json.loads(str(tool_message.get("content") or "{}"))
                routes = payload.get("routes") or (
                    payload.get("sanitized_result") or {}
                ).get("routes")
                duration = int(routes[0]["duration_minutes"])
                # 吸收补查结果：按实际路线时长安排停留点的结束时间。
                placement = self._itinerary["days"][0]["placements"][0]
                start = placement["planned_start"]
                hour, minute = int(start[11:13]), int(start[14:16]) + duration + 60
                placement["planned_end"] = (
                    f"{start[:11]}{hour + minute // 60:02d}:{minute % 60:02d}:00+08:00"
                )
                yield {"type": "finish", "content": json.dumps(self._itinerary, ensure_ascii=False), "tool_calls": []}
                return
            if self._redo_request is not None and self.composition_calls == 1:
                self._emitted_redo = True
                yield {"type": "finish", "content": json.dumps(self._redo_request, ensure_ascii=False), "tool_calls": []}
                return
            itinerary = self._itinerary
            if self._emitted_redo:
                # 返研后继续组合：草稿改为引用重做后的新候选。
                payload = json.loads(json.dumps(self._itinerary, ensure_ascii=False))
                for day in payload["days"]:
                    for placement in day["placements"]:
                        placement["candidate_id"] = placement["candidate_id"].replace(
                            "supply_visit_", "redo_visit_"
                        )
                itinerary = payload
            yield {"type": "finish", "content": json.dumps(itinerary, ensure_ascii=False), "tool_calls": []}
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
        candidates = self._supply[worker]
        if worker == "destination_researcher" and any(
            "返研请求" in str(m.get("content", "")) for m in messages
        ):
            candidates = self._redo_supply
        yield {"type": "finish", "content": json.dumps({"candidates": candidates, "source_records": [], "fact_assertions": [], "field_provenance": []}, ensure_ascii=False), "tool_calls": []}


async def _run_research_feedback(monkeypatch, model: FeedbackModel):
    """装配离线边界并跑通真实图（理解 → 方案确认 → 串行研究 → 组合）。"""
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
    route_calls: list[dict] = []

    async def search(query):
        return {"success": True, "query": query, "provider": "fixture", "results": []}

    registry.register("global_place_search", "查询地点", {"type": "object", "properties": {"query": {"type": "string"}}}, search, manifest=ToolManifest(tool_name="global_place_search"))

    async def route_search(**arguments):
        route_calls.append(dict(arguments))
        return {"success": True, "routes": [
            {"duration_minutes": 45, "mode": "drive", "from": arguments.get("from"), "to": arguments.get("to")}
        ]}

    registry.register("global_route_search", "查询路线", {
        "type": "object",
        "properties": {"from": {"type": "string"}, "to": {"type": "string"}},
    }, route_search, manifest=ToolManifest(tool_name="global_route_search"))

    async def search_flights(params):
        return {"success": True, "routes": []}

    registry.register("search_flights", "查询航班", {
        "type": "object", "properties": {"params": {"type": "object"}},
    }, search_flights, manifest=ToolManifest(tool_name="search_flights"))

    monkeypatch.setattr(execution, "get_tool_registry", lambda: registry)
    monkeypatch.setattr(react, "get_tool_registry", lambda: registry)
    monkeypatch.setattr(react, "apply_tool_exposure", lambda tools, name: ToolExposurePlan(False, name, tuple(item["schema"] for item in tools), "", 0, 0, len(tools), len(tools)))

    async def available(_selected):
        return registry.get_tools_as_schemas()

    for module in (destination, transport, accommodation, understanding_agent, itinerary):
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

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from travel_agent.planning.graph import build_travel_workflow
    from travel_agent.storage.delivery_bundle_store import InMemoryDeliveryBundleStore
    from travel_agent.storage.trip_run_store import InMemoryTripRunStore
    from travel_agent.runtime.run_contracts import TripRunStatus

    bundles, runs = InMemoryDeliveryBundleStore(), InMemoryTripRunStore()
    await runs.create_run(run_id="feedback-flow", session_id="feedback-flow", user_id="local", mode="deep")
    await runs.transition_status("feedback-flow", TripRunStatus.RUNNING)
    graph = build_travel_workflow().compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "feedback-flow", "plan_gate_enabled": True, "run_execution_store": LeaseStore(), "delivery_bundle_store": bundles, "trip_run_store": runs}}
    state = TravelAgentState(
        run_id="feedback-flow", session_id="feedback-flow",
        user_query="喜欢博物馆和街区漫步，不赶路。",
        controlled_trip_identity=IDENTITY,
    )
    from travel_agent.runtime.budget import reset_ledgers
    from travel_agent.runtime.journal import current_execution_lease

    token = current_execution_lease.set("lease")
    reset_ledgers()
    try:
        first = await graph.ainvoke(state, config)
        gate = first["__interrupt__"][0].value
        result = await graph.ainvoke(
            Command(resume={"action": "approve", "approval_token": gate["approval_token"]}),
            config,
        )
    finally:
        current_execution_lease.reset(token)
    return result, route_calls


def _itinerary_payload() -> dict:
    return {
        "itinerary_id": "offline_itinerary", "title": "杭州慢游", "duration_days": 2,
        "days": [
            {"day_id": "day_1", "day": 1, "date": "2026-11-05", "destination_id": "city_hangzhou", "placements": [{
                "placement_kind": "visit", "candidate_id": "supply_visit_01",
                "planned_start": "2026-11-05T09:30:00+08:00", "planned_end": "2026-11-05T11:00:00+08:00",
                "duration_minutes": 90, "selection_reason": "慢游首选",
            }], "day_design": {
                "focus": "街区与湖边慢游",
                "rationale": "按核心体验就近安排，不赶路",
                "free_time": [],
                "unresolved": ["运河游船当日晚班次未能核实，暂不安排"],
            }},
            {"day_id": "day_2", "day": 2, "date": "2026-11-06", "destination_id": "city_hangzhou", "placements": [{
                "placement_kind": "visit", "candidate_id": "supply_visit_02",
                "planned_start": "2026-11-06T09:30:00+08:00", "planned_end": "2026-11-06T11:00:00+08:00",
                "duration_minutes": 90, "selection_reason": "慢游次选",
            }]},
        ],
        "lodging_candidate_ids": [],
    }


def _supply() -> dict[str, list[dict]]:
    return {
        "destination_researcher": [
            _visit_candidate(1, "city_hangzhou", "杭州"),
            _visit_candidate(2, "city_hangzhou", "杭州"),
        ],
        "transport_researcher": [
            _transport_candidate(1, "city_hangzhou"),
        ],
        "accommodation_researcher": [
            _lodging_candidate(1, "city_hangzhou"),
        ],
    }


async def test_composition_supplementary_query_adjusts_arrangement(monkeypatch):
    """组合在工具循环内补查路线，并依据实际交通时间调整安排。"""
    model = FeedbackModel(
        identity=IDENTITY,
        supply=_supply(),
        redo_supply=[],
        itinerary=_itinerary_payload(),
        route_query=True,
    )
    result, route_calls = await _run_research_feedback(monkeypatch, model)

    # 工具真实执行过一次，参数来自组合模型的调用。
    assert len(route_calls) == 1
    assert route_calls[0]["from"] == "supply_place_01"
    # 补查结果进入组合模型的上下文（吸收），并据此调整停留点时间：
    # 09:30 出发 + 45 分钟实际路线 + 60 分钟停留 = 11:15 结束。
    assert "routes" in model.composition_transcripts[-1]
    placement = result["placement_skeleton"].days[0].placements[0]
    assert placement.planned_end.isoformat() == "2026-11-05T11:15:00+08:00"
    # 交通研究已查的市内实测路线（含耗时）对组合可读，供排时间窗口参考。
    assert "supply_transit_01" in model.composition_request
    assert '"duration_minutes":40' in model.composition_request
    # 组合完成后行程正常交付，目录与骨架一致；模型报告的未安排事项
    # 保留为未安排事项，不随说明重建而丢失。
    workspace = result["trip_workspace_v2"]
    assert workspace is not None
    assert result["agent_status"]["itinerary_planner"] == "completed"
    assert workspace.itinerary.unresolved == ["运河游船当日晚班次未能核实，暂不安排"]


async def test_research_redo_round_trip_replaces_erroneous_output(monkeypatch):
    """严重不可用的研究经组合反馈返回对应 Worker 重做，再继续组合。"""
    model = FeedbackModel(
        identity=IDENTITY,
        supply=_supply(),
        redo_supply=[_redo_candidate(1, "city_hangzhou"), _redo_candidate(2, "city_hangzhou")],
        itinerary=_itinerary_payload(),
        redo_request={
            "action": "request_research_redo",
            "worker_kind": "destination_researcher",
            "feedback": "候选与目的地不符，无法安排行程；请重新调查杭州的真实景点。",
        },
    )
    result, _ = await _run_research_feedback(monkeypatch, model)

    # 研究顺序：目的地 → 交通 → 住宿 → 目的地返研（第 2 轮）。
    assert model.worker_order == [
        "destination_researcher",
        "transport_researcher",
        "accommodation_researcher",
        "destination_researcher",
    ]
    # 返研轮的 Worker 读到反馈与上一轮错误成果。
    redo_request_text = model.worker_requests["destination_researcher"]
    assert "返研请求" in redo_request_text
    assert "组合反馈" in redo_request_text
    assert "上一轮错误成果" in redo_request_text
    # 图状态：返研轮完成、返研请求被消费、返研计数记一次。
    assert result["agent_status"]["destination_researcher_r2"] == "completed"
    assert result["agent_status"]["itinerary_planner"] == "completed"
    assert (result["research_redo_requests"] or {}) == {}
    assert result["research_redo_rounds"] == {"destination_researcher": 1}
    assert "day_design.unresolved" in model.composition_request
    assert result["trip_workspace_v2"].itinerary.unresolved == [
        "运河游船当日晚班次未能核实，暂不安排"
    ]
    assert any(
        key.startswith("destination_researcher_r2@")
        for key in result["research_packets"]
    )
    # 被替代的旧候选退出目录与最终工作区，其他 Worker 的成果保留。
    catalog_ids = set(result["recommendation_catalog"].candidate_index())
    assert "supply_visit_01" not in catalog_ids
    assert "supply_visit_02" not in catalog_ids
    assert "redo_visit_01" in catalog_ids
    assert "redo_visit_02" in catalog_ids
    assert "supply_transit_01" in catalog_ids
    workspace = result["trip_workspace_v2"]
    assert workspace is not None
    assert [stop.place_id for stop in workspace.itinerary.visit_stops] == [
        "redo_place_01",
        "redo_place_02",
    ]
    # 组合继续后使用新成果完成骨架与物化。
    assert result["placement_skeleton"] is not None


def test_replaced_worker_results_exit_catalog_but_others_retained():
    """目录重建时被替代的旧轮次整体退出，其他 Worker 与目录内补查成果保留。"""
    from travel_agent.planning.requirements.generation_contracts import PlanningGeneration

    old_destination = make_packet(
        "dest_r1", worker="destination_researcher", entities=(("supply_visit_01", "tokyo"),)
    ).model_copy(update={"task_id": "destination_researcher"})
    new_destination = make_packet(
        "dest_r2", worker="destination_researcher", entities=(("redo_visit_01", "tokyo"),)
    ).model_copy(update={"task_id": "destination_researcher_r2"})
    transport = make_packet("trans", worker="transport_researcher", entities=(("supply_transit_01", "tokyo"),))
    connector = make_packet("connector", worker="transport_researcher", entities=(("connector_leg_01", "tokyo"),))
    previous = make_catalog(old_destination, transport, connector)
    state = TravelAgentState(
        run_id="run_test",
        planning_generation=PlanningGeneration(generation_id="generation_test", revision=1),
        fact_data_revision=1,
        research_packets={
            "destination_researcher@generation_test": old_destination,
            "destination_researcher_r2@generation_test": new_destination,
            "transport_researcher@generation_test": transport,
        },
        recommendation_catalog=previous,
    )
    catalog, _impacts = build_candidate_catalog(state)
    candidates = set(catalog.candidate_index())
    # 被替代的目的地旧候选不回流。
    assert "supply_visit_01" not in candidates
    assert "redo_visit_01" in candidates
    # 其他 Worker 的成果保留。
    assert "supply_transit_01" in candidates
    # 组合接驳补全产生的目录内 packet（不在 state 里）未被误删。
    assert "connector_leg_01" in candidates


def test_redo_without_new_packet_exits_erroneous_results():
    """返研请求已接受但返研轮没有产出 packet 时，错误旧成果同样退出目录。"""
    from travel_agent.planning.requirements.generation_contracts import PlanningGeneration

    old_destination = make_packet(
        "dest_r1", worker="destination_researcher", entities=(("supply_visit_01", "tokyo"),)
    ).model_copy(update={"task_id": "destination_researcher"})
    transport = make_packet("trans", worker="transport_researcher", entities=(("supply_transit_01", "tokyo"),))
    previous = make_catalog(old_destination, transport)
    state = TravelAgentState(
        run_id="run_test",
        planning_generation=PlanningGeneration(generation_id="generation_test", revision=1),
        fact_data_revision=1,
        research_packets={
            "destination_researcher@generation_test": old_destination,
            "transport_researcher@generation_test": transport,
        },
        recommendation_catalog=previous,
        research_redo_rounds={"destination_researcher": 1},
    )
    catalog, _impacts = build_candidate_catalog(state)
    candidates = set(catalog.candidate_index())
    # 组合已判定不可用且已返研：旧候选不得作为「未入选备选」继续供给。
    assert "supply_visit_01" not in candidates
    assert "supply_transit_01" in candidates


def test_latest_worker_packet_is_scoped_to_current_generation():
    """返研对照的错误成果只从当前规划版本中选取，旧版本轮次不参与。"""
    from travel_agent.planning.requirements.generation_contracts import PlanningGeneration
    from travel_agent.planning.research.feedback import latest_worker_packet

    stale_generation = make_packet(
        "dest_stale_r2",
        worker="destination_researcher",
        generation="generation_old",
        entities=(("stale_visit", "tokyo"),),
    ).model_copy(update={"task_id": "destination_researcher_r2"})
    current_generation = make_packet(
        "dest_r1", worker="destination_researcher", entities=(("supply_visit_01", "tokyo"),)
    ).model_copy(update={"task_id": "destination_researcher"})
    state = TravelAgentState(
        run_id="run_test",
        planning_generation=PlanningGeneration(generation_id="generation_test", revision=1),
        fact_data_revision=1,
        research_packets={
            "destination_researcher_r2@generation_old": stale_generation,
            "destination_researcher@generation_test": current_generation,
        },
    )
    key, packet = latest_worker_packet(state, "destination_researcher")
    assert key == "destination_researcher@generation_test"
    assert packet.research_packet_id == "dest_r1"


async def test_failed_composition_is_not_re_entered_after_research_window_closes():
    """研究窗口关闭后跳组合：组合已失败时收敛到收口，不反复重入。"""
    from datetime import datetime, timedelta, timezone

    from travel_agent.planning.requirements.generation_contracts import PlanningGeneration
    from travel_agent.planning.research.dispatch import dispatcher_node
    from travel_agent.runtime.budget import RunBudgetSnapshot
    from travel_agent.runtime.deadlines import RunDeadlineSnapshot

    now = datetime.now(timezone.utc)
    # 墙钟已过 closeout（研究窗口关闭）但未到 composition（组合窗口仍开）。
    authorized = now - timedelta(seconds=1000)
    snapshot = RunDeadlineSnapshot(
        draft_id="draft",
        planning_authorized_at=authorized,
        target_at=authorized + timedelta(seconds=600),
        closeout_at=authorized + timedelta(seconds=900),
        composition_at=authorized + timedelta(seconds=1200),
        delivery_deadline_at=authorized + timedelta(seconds=1500),
        target_seconds=600,
        closeout_seconds=900,
        composition_seconds=1200,
        delivery_deadline_seconds=1500,
        checkpointed_elapsed_seconds=1000.0,
        last_observed_at=now,
    )

    destination_packet = make_packet(
        "dest", worker="destination_researcher", entities=(("supply_visit_01", "tokyo"),)
    ).model_copy(update={"task_id": "destination_researcher"})

    def state_for(itinerary_status: str) -> TravelAgentState:
        return TravelAgentState(
            run_id="run_test",
            execution_plan=[["destination_researcher"], ["itinerary_planner"]],
            current_plan_step=1,
            planning_generation=PlanningGeneration(generation_id="generation_test", revision=1),
            fact_data_revision=1,
            research_packets={"destination_researcher@generation_test": destination_packet},
            run_deadline=snapshot,
            run_budget=RunBudgetSnapshot(enforce_limits=True, max_tool_calls=20),
            trip_workspace_v2=None,
            agent_status={
                "destination_researcher": "completed",
                "itinerary_planner": itinerary_status,
            },
        )

    # 组合待续：跳到组合步骤并重建目录。
    pending = await dispatcher_node(state_for("pending"))
    assert pending["next_agent"] == "itinerary_planner"
    assert pending["current_plan_step"] == 1
    assert pending["recommendation_catalog"] is not None
    # 组合已失败：不再重入，收敛到预算与交付收口。
    failed = await dispatcher_node(state_for("failed"))
    assert failed["next_agent"] == "to_check"


def test_upstream_view_keeps_only_latest_research_round():
    """上游研究视图只保留各 Worker 的最新轮次。"""
    destination_r1 = make_packet(
        "dest_r1", worker="destination_researcher", entities=(("visit_old", "tokyo"),)
    ).model_copy(update={"task_id": "destination_researcher"})
    destination_r2 = make_packet(
        "dest_r2", worker="destination_researcher", entities=(("visit_new", "tokyo"),)
    ).model_copy(update={"task_id": "destination_researcher_r2"})
    transport = make_packet("trans", worker="transport_researcher", entities=(("transit_old", "tokyo"),))
    view = project_research_context(
        {
            "destination_researcher@generation_test": destination_r1,
            "destination_researcher_r2@generation_test": destination_r2,
            "transport_researcher@generation_test": transport,
        },
        worker_kind="accommodation_researcher",
        run_id="run_test",
        generation_id="generation_test",
        destination_ids=["tokyo"],
    )
    kinds_and_ids = {
        (candidate["candidate_kind"], candidate["candidate_id"])
        for coordination in view.coordination
        for candidate in coordination.candidates
    }
    assert ("visit", "visit_new") in kinds_and_ids
    assert ("visit", "visit_old") not in kinds_and_ids
    assert ("transport", "transit_old") in kinds_and_ids


def test_redo_request_is_visible_in_workspace_progress():
    """组合发出的返研请求以组合卡片可见的结论展示。"""
    status, content, preview = worker_result(
        "itinerary_planner",
        {"research_redo_requests": {"destination_researcher": {"feedback": "候选与目的地不符"}},
         "agent_status": {"itinerary_planner": "pending"}},
    )
    assert status == "completed"
    assert "目的地调研" in content
    assert "重做" in content
    assert preview == []


def test_redo_round_is_capped_and_parses_only_valid_requests():
    from travel_agent.planning.itinerary.node import _research_redo_update
    from travel_agent.planning.research.feedback import ResearchRedoRequest

    state = TravelAgentState(
        run_id="run_test",
        research_redo_rounds={"destination_researcher": RESEARCH_REDO_ROUNDS_CAP},
        agent_assignments={"destination_researcher": {"objective": "调查景点"}},
    )
    request = ResearchRedoRequest(
        worker_kind="destination_researcher", feedback="候选不可用"
    )
    with pytest.raises(ValueError, match="beyond the allowed rounds"):
        _research_redo_update(state, request, "itinerary_planner", {})

    update = _research_redo_update(
        state.model_copy(update={"research_redo_rounds": {}}),
        request,
        "itinerary_planner",
        {},
    )
    assert update["next_agent"] == "destination_researcher"
    assert update["agent_assignments"]["destination_researcher_r2"]["objective"] == "调查景点"
    assert update["research_redo_rounds"] == {"destination_researcher": 1}
    assert update["agent_status"]["itinerary_planner"] == "pending"

    # 解析合同：只有合法的返研请求被识别。
    assert parse_research_redo_request(json.dumps({
        "action": "request_research_redo",
        "worker_kind": "transport_researcher",
        "feedback": "班次全部不可用",
    })) == {"worker_kind": "transport_researcher", "feedback": "班次全部不可用"}
    assert parse_research_redo_request(json.dumps({"days": []})) is None
    assert parse_research_redo_request("not json") is None


def test_redo_round_runs_under_composition_model_window():
    """返研轮使用组合模型窗口，可在研究窗口关闭后继续。"""
    from travel_agent.planning.execution import _model_window_for_node

    assignments = {
        "destination_researcher": {"objective": "调查景点"},
        "destination_researcher_r2": {"objective": "调查景点"},
    }
    redo_state = TravelAgentState(agent_assignments=assignments)
    plain_state = TravelAgentState(agent_assignments={"destination_researcher": {"objective": "调查景点"}})
    assert _model_window_for_node("destination_researcher", redo_state) == "composition"
    assert _model_window_for_node("destination_researcher", plain_state) == "research"
    assert _model_window_for_node("itinerary_planner", plain_state) == "composition"
    assert _model_window_for_node("destination_researcher", TravelAgentState()) == "research"
