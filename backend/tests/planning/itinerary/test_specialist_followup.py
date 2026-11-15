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


def _rail_state():
    return _state().model_copy(update={
        "recommendation_catalog": make_catalog(),
        "controlled_trip_identity": {
            "start_date": "2026-10-10",
            "end_date": "2026-10-14",
            "origin": {"place_id": "city_guangzhou", "name": "广州", "country_code": "CN"},
            "destinations": [
                {"place_id": "city_haikou", "name": "海口", "country_code": "CN"},
                {"place_id": "city_sanya", "name": "三亚", "country_code": "CN"},
            ],
        },
    })


def _ticket_row(train_code="D7201", *, from_name="海口东", from_code="HMQ",
                to_name="三亚", to_code="SEQ", departure="09:20", arrival="11:01",
                duration=101, price=96.0):
    return {
        "train_code": train_code,
        "from_name": from_name,
        "from_code": from_code,
        "to_name": to_name,
        "to_code": to_code,
        "departure_time": departure,
        "arrival_time": arrival,
        "duration_minutes": duration,
        "min_price_cny": price,
        "second_class_price_cny": price,
        "fare_summary": "二等座 有 96元",
    }


def _ticket_envelope(rows, *, date="2026-10-10", audit_id="rail-audit"):
    envelope = build_tool_execution_envelope(
        tool_name="get-tickets", server_name="12306-train", source="mcp", status="success",
        arguments={"date": date, "fromStation": "VUQ", "toStation": "SEQ"},
        result={
            "success": True, "provider": "12306", "tool_name": "get-tickets", "date": date,
            "from_station": "VUQ", "to_station": "SEQ", "bookable_train_count": len(rows),
            "returned_train_count": len(rows), "results": rows,
        },
        audit_id=audit_id,
    )
    envelope["metadata"]["evidence_allowed"] = True
    return envelope


@pytest.mark.asyncio
async def test_local_connector_followup_does_not_compile_rail_results(monkeypatch):
    from travel_agent.planning.itinerary.connectors import LocalConnectorGap

    state = _state()
    gap = LocalConnectorGap.model_validate({
        "gap_id": "gap", "day_id": "day_1", "day_date": "2026-10-10",
        "destination_id": "destination_tokyo", "from_entry_key": "left", "to_entry_key": "right",
        "from_place_id": "left", "to_place_id": "right",
        "departure_time": "2026-10-10T09:00:00+09:00", "latest_arrival_time": "2026-10-10T10:00:00+09:00",
        "allowed_transport_classes": ["public_transit"], "preferred_transport_class": "public_transit",
        "weather_data_revision": 0,
    })
    monkeypatch.setattr(followup, "get_model_router", lambda: None)
    monkeypatch.setattr(followup, "llm_for_task", lambda *args, **kwargs: object())
    monkeypatch.setattr(followup, "get_available_tools", lambda: _available())
    monkeypatch.setattr(followup, "filter_tools_for_agent", lambda tools, agent: tools)

    async def react(**kwargs):
        return SimpleNamespace(outcome=followup.ReactOutcome.FINAL_ANSWER, content="查询完成", error=None,
                               tool_results=[_ticket_envelope([_ticket_row()])])

    monkeypatch.setattr(followup, "streaming_react_loop", react)
    response, catalog = await followup.research_transport_followup(
        state, question="市内接驳", arrangement="上午", gaps=[gap], destination_id="destination_tokyo",
    )
    assert response["sanitized_result"]["routes"] == []
    assert catalog == state.recommendation_catalog


def test_rail_station_fallback_uses_offline_station_groups():
    from travel_agent.integrations.rail.stations import city_station_telecodes
    from travel_agent.planning.research.transport.rail.binding import rail_ticket_station_pairs
    from travel_agent.planning.research.transport.rail.parsing import (
        _builtin_station_telecode, _builtin_station_telecode_candidates,
    )

    assert _builtin_station_telecode("海口市") == "VUQ"
    assert _builtin_station_telecode("三亚") == "SEQ"
    assert _builtin_station_telecode("琼海") == "QYQ"
    assert _builtin_station_telecode("海口东站") == "HMQ"
    assert _builtin_station_telecode("儋州") in city_station_telecodes("儋州")
    assert "HMQ" in city_station_telecodes("海口")
    assert _builtin_station_telecode_candidates("上海")[:2] == ["AOH", "SHH"]
    assert rail_ticket_station_pairs(
        origin_name="海口", dest_name="三亚", from_code="VUQ", to_code="SEQ",
    )[0] == ("VUQ", "SEQ")


@pytest.mark.asyncio
async def test_followup_compiles_rail_results_and_materializes_lineage(monkeypatch):
    from travel_agent.planning.delivery.fact_projection import build_fact_snapshot, workspace_for_public_projection
    from travel_agent.planning.itinerary.materialize import materialize_trip_workspace
    from travel_agent.tools.content import compact_tool_content_for_model

    state = _rail_state()
    rows = [{"truncated": True}, _ticket_row(), _ticket_row("D7203", departure="10:20", arrival="12:01")]
    envelope = _ticket_envelope(rows)
    monkeypatch.setattr(followup, "get_model_router", lambda: None)
    monkeypatch.setattr(followup, "llm_for_task", lambda *args, **kwargs: object())
    monkeypatch.setattr(followup, "get_available_tools", lambda: _available())
    monkeypatch.setattr(followup, "filter_tools_for_agent", lambda tools, agent: tools)

    async def react(**kwargs):
        return SimpleNamespace(
            outcome=followup.ReactOutcome.FINAL_ANSWER, content="已查到海南动车。",
            tool_results=[envelope], error=None,
        )

    monkeypatch.setattr(followup, "streaming_react_loop", react)
    response, catalog = await followup.research_transport_followup(
        state, question="海口去三亚的动车？", arrangement="10月10日前往三亚", destination_id="city_haikou",
    )
    routes = response["sanitized_result"]["routes"]
    assert response["status"] == "success"
    assert len(routes) == 2
    route = routes[0]
    assert route["route_id"] == "12306:2026-10-10:D7201:HMQ:SEQ"
    assert route["service_number"] == "D7201"
    assert route["from_endpoint"] == {"name": "海口东", "station_code": "HMQ", "place_id": "12306:HMQ"}
    assert route["to_endpoint"]["name"] == "三亚"
    assert route["departure_at"] == "2026-10-10T09:20:00+08:00"
    assert route["arrival_at"] == "2026-10-10T11:01:00+08:00"
    assert route["duration_minutes"] == 101
    assert route["total_cost_cny"] == 96
    assert route["from"] == "海口东" and route["to"] == "三亚"
    assert route["sources"] and route["observed_at"]
    compact = json.loads(compact_tool_content_for_model(response))
    model_route = compact["sanitized_result"]["routes"][0]
    for field in ("candidate_id", "route_id", "from_endpoint", "to_endpoint", "departure_at",
                  "arrival_at", "duration_minutes", "service_number", "total_cost_cny"):
        assert model_route[field] == route[field]
    packet = catalog.research_packets[-1]
    candidate = catalog.candidate_index()[model_route["candidate_id"]]
    assert candidate.destination_id == "city_sanya"
    assert candidate.segments[0].service_number == "D7201"
    source = next(item for item in packet.source_records if item.source_record_id in candidate.source_record_ids)
    assert source.snapshot == envelope
    assert source.tool_audit_id == "rail-audit"
    candidate_facts = [fact for fact in packet.fact_assertions if fact.entity_ref.entity_id == candidate.candidate_id]
    assert candidate_facts and all(fact.source_links for fact in candidate_facts)
    assert all(link.source_locator.startswith("sanitized_result.results[1]") or link.source_locator == "sanitized_result.date"
               for fact in candidate_facts for link in fact.source_links)
    assert {item.field_path for item in packet.field_provenance if item.entity_ref.entity_id == candidate.candidate_id} == set(candidate.field_paths)

    draft = ItineraryCompositionDraft.model_validate({
        "itinerary_id": "hainan", "title": "海南", "duration_days": 1,
        "days": [{"day_id": "day_1", "day": 1, "date": "2026-10-10", "destination_id": "city_sanya",
                  "placements": [{"placement_kind": "transport", "candidate_id": model_route["candidate_id"]}]}],
    })
    workspace = materialize_trip_workspace(
        run_id=state.run_id, workspace_revision=1, composition=draft, catalog=catalog,
        requirements="海南", composition_mutations=[],
    )
    leg = workspace.itinerary.transport_legs[0]
    assert leg.lineage.candidate_id == candidate.candidate_id
    assert leg.lineage.source_record_ids == candidate.source_record_ids
    assert leg.from_endpoint.name == "海口东"
    assert leg.segments[0].service_number == "D7201"
    public_workspace = workspace_for_public_projection(workspace, build_fact_snapshot(workspace))
    assert public_workspace.itinerary.transport_legs[0].total_cost_cny == 96


@pytest.mark.asyncio
async def test_followup_reuses_already_compiled_train_for_composition(monkeypatch):
    from travel_agent.planning.research.transport.rail.followup import compile_rail_followup_packet

    state = _rail_state()
    envelope = _ticket_envelope([_ticket_row()])
    packet = compile_rail_followup_packet(
        state=state, catalog=state.recommendation_catalog, envelope=envelope,
        task_id="prior", existing_candidate_ids=set(),
    )
    payload = packet.model_dump(mode="python")
    payload["candidates"][0]["candidate_id"] = "existing_model_candidate"
    for fact in payload["fact_assertions"]:
        fact["entity_ref"]["entity_id"] = "existing_model_candidate"
    for provenance in payload["field_provenance"]:
        provenance["entity_ref"]["entity_id"] = "existing_model_candidate"
    packet = type(packet).model_validate(payload)
    state = state.model_copy(update={"recommendation_catalog": make_catalog(packet)})
    monkeypatch.setattr(followup, "get_model_router", lambda: None)
    monkeypatch.setattr(followup, "llm_for_task", lambda *args, **kwargs: object())
    monkeypatch.setattr(followup, "get_available_tools", lambda: _available())
    monkeypatch.setattr(followup, "filter_tools_for_agent", lambda tools, agent: tools)

    async def react(**kwargs):
        return SimpleNamespace(
            outcome=followup.ReactOutcome.FINAL_ANSWER, content="已查到动车。",
            tool_results=[envelope], error=None,
        )

    monkeypatch.setattr(followup, "streaming_react_loop", react)
    response, catalog = await followup.research_transport_followup(
        state, question="海口到三亚", arrangement="动车", service_date="2026-10-10",
    )
    assert response["sanitized_result"]["routes"][0]["candidate_id"] == packet.candidates[0].candidate_id
    assert response["sanitized_result"]["routes"][0]["service_number"] == "D7201"
    assert catalog == state.recommendation_catalog
    assert response["followup_packets"] == []


@pytest.mark.asyncio
async def test_followup_reuses_matching_rail_rows_and_keeps_new_options(monkeypatch):
    from travel_agent.planning.research.transport.rail.followup import compile_rail_followup_packet

    state = _rail_state()
    first = _ticket_envelope([_ticket_row()], audit_id="initial")
    packet = compile_rail_followup_packet(
        state=state, catalog=state.recommendation_catalog, envelope=first,
        task_id="prior", existing_candidate_ids=set(),
    )
    state = state.model_copy(update={"recommendation_catalog": make_catalog(packet)})
    monkeypatch.setattr(followup, "get_model_router", lambda: None)
    monkeypatch.setattr(followup, "llm_for_task", lambda *args, **kwargs: object())
    monkeypatch.setattr(followup, "get_available_tools", lambda: _available())
    monkeypatch.setattr(followup, "filter_tools_for_agent", lambda tools, agent: tools)

    async def react(**kwargs):
        return SimpleNamespace(
            outcome=followup.ReactOutcome.FINAL_ANSWER, content="已查到两班动车。", error=None,
            tool_results=[_ticket_envelope([_ticket_row(), _ticket_row("D7203")], audit_id="again")],
        )

    monkeypatch.setattr(followup, "streaming_react_loop", react)
    response, catalog = await followup.research_transport_followup(
        state, question="海口到三亚", arrangement="动车", service_date="2026-10-10",
    )
    routes = response["sanitized_result"]["routes"]
    assert {route["service_number"] for route in routes} == {"D7201", "D7203"}
    assert len(catalog.candidate_index()) == 2
    assert len(response["followup_packets"]) == 1
    assert len(response["followup_packets"][0]["candidates"]) == 1
    assert followup._restore_catalog(state.recommendation_catalog, response) == catalog


@pytest.mark.asyncio
async def test_followup_keeps_real_routes_when_more_than_five_are_returned(monkeypatch):
    from travel_agent.tools.content import compact_tool_content_for_model

    state = _rail_state()
    monkeypatch.setattr(followup, "get_model_router", lambda: None)
    monkeypatch.setattr(followup, "llm_for_task", lambda *args, **kwargs: object())
    monkeypatch.setattr(followup, "get_available_tools", lambda: _available())
    monkeypatch.setattr(followup, "filter_tools_for_agent", lambda tools, agent: tools)
    envelopes = [
        _ticket_envelope([_ticket_row(f"D72{i:02d}")], audit_id=f"rail-{i}")
        for i in range(7)
    ]

    async def react(**kwargs):
        return SimpleNamespace(
            outcome=followup.ReactOutcome.FINAL_ANSWER, content="已查到多班动车。",
            tool_results=envelopes, error=None,
        )

    monkeypatch.setattr(followup, "streaming_react_loop", react)
    response, catalog = await followup.research_transport_followup(
        state, question="海口到三亚", arrangement="动车", service_date="2026-10-10",
    )
    routes = response["sanitized_result"]["routes"]
    assert len(routes) == len(catalog.candidate_index()) == 7
    assert all(route["candidate_id"] in catalog.candidate_index() for route in routes)
    compact = json.loads(compact_tool_content_for_model(response))
    compact_routes = compact["sanitized_result"]["routes"]
    assert compact_routes and all(route["candidate_id"] in catalog.candidate_index() for route in compact_routes)
    assert compact_routes[0]["from_endpoint"]["name"] == "海口东"


def test_rail_compiler_dates_station_identity_and_option_limit():
    from travel_agent.planning.research.transport.rail.followup import compile_rail_followup_packet

    state = _rail_state()
    rows = [
        _ticket_row("D7201", departure="22:30", arrival="00:10", duration=100),
        _ticket_row("D7202", departure="10:00", arrival="11:30", duration=90),
        _ticket_row("D7203", departure="12:00", arrival="13:30", duration=90),
        _ticket_row("D7204", departure="14:00", arrival="15:30", duration=90),
    ]
    def compile_one(envelope, existing=None):
        return compile_rail_followup_packet(
            state=state, catalog=state.recommendation_catalog, envelope=envelope,
            task_id="fixture", existing_candidate_ids=existing or set(),
        )

    packet = compile_one(_ticket_envelope(rows))
    assert packet is not None and len(packet.candidates) == 3
    overnight = compile_one(_ticket_envelope(rows[:1]))
    assert overnight.candidates[0].arrival_at.isoformat() == "2026-10-11T00:10:00+08:00"
    first_id = overnight.candidates[0].candidate_id
    tomorrow = compile_one(_ticket_envelope(rows[:1], date="2026-10-11"))
    other_station = compile_one(_ticket_envelope([_ticket_row(from_name="海口", from_code="VUQ")]))
    assert len({first_id, tomorrow.candidates[0].candidate_id, other_station.candidates[0].candidate_id}) == 3
    assert compile_one(_ticket_envelope(rows[:1]), {first_id}) is None
    long_trip = compile_one(_ticket_envelope([
        _ticket_row("K123", departure="10:00", arrival="11:00", duration=1500),
    ]))
    assert long_trip.candidates[0].arrival_at.isoformat() == "2026-10-11T11:00:00+08:00"
    assert compile_rail_followup_packet(
        state=state, catalog=state.recommendation_catalog, envelope=_ticket_envelope(rows[:1]),
        task_id="fixture", existing_candidate_ids=set(), service_date="2026-10-11",
    ) is None


@pytest.mark.asyncio
async def test_rail_scope_controls_materialized_transport_alternatives(monkeypatch):
    from travel_agent.planning.itinerary.materialize import materialize_trip_workspace
    from travel_agent.planning.research.transport.rail.followup import compile_rail_followup_packet

    state = _rail_state()
    envelope = _ticket_envelope([_ticket_row()])
    envelope["metadata"].update({
        "rail_selected_train": {"train_code": "D7201", "from_code": "HMQ", "to_code": "SEQ"},
        "rail_route_leg": {"leg_role": "inter_destination", "from_place_id": "city_haikou",
                           "to_place_id": "city_sanya", "service_date": "2026-10-10", "cross_day_required": False},
        "rail_scope_id": "a" * 64,
    })
    packet = compile_rail_followup_packet(
        state=state, catalog=state.recommendation_catalog, envelope=envelope,
        task_id="initial", existing_candidate_ids=set(),
    )
    initial = packet.candidates[0]
    assert initial.provider_evidence_scope_id == "a" * 64
    state = state.model_copy(update={"recommendation_catalog": make_catalog(packet)})
    monkeypatch.setattr(followup, "get_model_router", lambda: None)
    monkeypatch.setattr(followup, "llm_for_task", lambda *args, **kwargs: object())
    monkeypatch.setattr(followup, "get_available_tools", lambda: _available())
    monkeypatch.setattr(followup, "filter_tools_for_agent", lambda tools, agent: tools)

    async def react(**kwargs):
        return SimpleNamespace(
            outcome=followup.ReactOutcome.FINAL_ANSWER, content="还有一班动车。", error=None,
            tool_results=[_ticket_envelope([_ticket_row("D7203")], audit_id="alternate")],
        )

    monkeypatch.setattr(followup, "streaming_react_loop", react)
    response, catalog = await followup.research_transport_followup(
        state, question="海口到三亚还有什么车次？", arrangement="三亚首日", service_date="2026-10-10",
    )
    alternate_id = response["sanitized_result"]["routes"][0]["candidate_id"]
    assert catalog.candidate_index()[alternate_id].provider_evidence_scope_id == initial.provider_evidence_scope_id
    draft = ItineraryCompositionDraft.model_validate({
        "itinerary_id": "hainan", "title": "海南", "duration_days": 1,
        "days": [{"day_id": "day_1", "day": 1, "date": "2026-10-10", "destination_id": "city_sanya",
                  "placements": [{"placement_kind": "transport", "candidate_id": initial.candidate_id}]}],
    })
    workspace = materialize_trip_workspace(
        run_id=state.run_id, workspace_revision=1, composition=draft, catalog=catalog,
        requirements="海南", composition_mutations=[],
    )
    slot = next(item for item in workspace.selection_slots if item.slot_type == "transport")
    assert {item.candidate_id for item in slot.options} == {initial.candidate_id, alternate_id}


def test_rail_compiler_reuses_matching_existing_rail_scope():
    from travel_agent.planning.research.transport.rail.followup import compile_rail_followup_packet

    state = _rail_state()
    def compile_one(catalog, envelope):
        return compile_rail_followup_packet(
            state=state, catalog=catalog, envelope=envelope, task_id="fixture", existing_candidate_ids=set(),
        )

    original = compile_one(state.recommendation_catalog, _ticket_envelope([_ticket_row()]))
    candidate = original.candidates[0].model_copy(update={"provider_evidence_scope_id": "a" * 64})
    scoped_catalog = make_catalog(original.model_copy(update={"candidates": [candidate]}))
    alternate = compile_one(scoped_catalog, _ticket_envelope([
        _ticket_row("D7203", from_name="海口", from_code="VUQ"),
    ], audit_id="other"))
    assert alternate.candidates[0].provider_evidence_scope_id == "a" * 64
    tomorrow = compile_one(scoped_catalog, _ticket_envelope([_ticket_row("D7203")], date="2026-10-11"))
    assert tomorrow.candidates[0].provider_evidence_scope_id is None
    reverse = compile_one(scoped_catalog, _ticket_envelope([
        _ticket_row("D7204", from_name="三亚", from_code="SEQ", to_name="海口东", to_code="HMQ"),
    ]))
    assert reverse.candidates[0].destination_id == "city_haikou"
    assert reverse.candidates[0].provider_evidence_scope_id is None


def test_followup_same_day_train_does_not_inherit_overnight_scope():
    from travel_agent.planning.research.transport.rail.followup import compile_rail_followup_packet

    state = _rail_state()
    night = _ticket_envelope([
        _ticket_row("D7201", departure="22:30", arrival="00:10", duration=100),
    ])
    night["metadata"].update({
        "rail_selected_train": {"train_code": "D7201", "from_code": "HMQ", "to_code": "SEQ"},
        "rail_route_leg": {"leg_role": "inter_destination", "from_place_id": "city_haikou",
                           "to_place_id": "city_sanya", "service_date": "2026-10-10", "cross_day_required": True},
        "rail_scope_id": "c" * 64,
    })
    overnight = compile_rail_followup_packet(
        state=state, catalog=state.recommendation_catalog, envelope=night,
        task_id="night", existing_candidate_ids=set(),
    )
    assert overnight.candidates[0].provider_evidence_scope_id == "c" * 64
    catalog = make_catalog(overnight)
    day = compile_rail_followup_packet(
        state=state, catalog=catalog, envelope=_ticket_envelope([_ticket_row("D7203")], audit_id="day"),
        task_id="day", existing_candidate_ids=set(),
    )
    assert day.candidates[0].provider_evidence_scope_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("reference_only", [False, True])
async def test_rail_discovery_preserves_only_target_date_ticket_envelope(monkeypatch, reference_only):
    from datetime import date, datetime, timezone
    from travel_agent.planning.research.provider_contracts import ProviderRouteLegScope
    from travel_agent.planning.research.transport.rail import binding

    state = _rail_state()
    leg = ProviderRouteLegScope(
        leg_role="inter_destination", from_place_id="city_haikou", to_place_id="city_sanya",
        service_date=date.fromisoformat("2026-11-30" if reference_only else "2026-10-10"),
    )
    monkeypatch.setattr(binding, "get_tool_registry", lambda: SimpleNamespace(
        has_tool=lambda name: name == "get-tickets",
    ))
    async def execute(name, arguments, **kwargs):
        if arguments["fromStation"] == "TEMPORAL_PREFLIGHT":
            return {"status": "reference_only", "metadata": {}}
        return _ticket_envelope([_ticket_row()], date=arguments["date"])

    async def locate(**kwargs):
        return (20.0, 110.3) if kwargs["telecode"] == "HMQ" else (18.3, 109.5)

    monkeypatch.setattr(binding, "execute_tool", execute)
    monkeypatch.setattr(binding, "_locate_rail_station", locate)
    messages, results, references = [], [], []
    identities = {item["place_id"]: item for item in state.controlled_trip_identity["destinations"]}
    bound = await binding._bind_one_rail_leg(
        state=state, messages=messages, tool_context={}, authoritative_tool_results=results,
        reference_services=references, scoped_leg=leg, identity_by_place_id=identities,
        station_code_cache={}, station_point_cache={}, now=datetime(2026, 10, 1, tzinfo=timezone.utc),
        scope_id="c" * 64,
    )
    if reference_only:
        assert not bound
        assert references and not any(item.get("tool_name") == "get-tickets" for item in results)
    else:
        assert bound
        assert [item["tool_name"] for item in results] == ["domestic_rail_search", "get-tickets"]
        original = results[1]
        assert original["sanitized_result"]["date"] == "2026-10-10"
        assert original["metadata"]["rail_selected_train"]["train_code"] == "D7201"
        assert original["metadata"]["rail_route_leg"] == leg.model_dump(mode="json")
        assert original["metadata"]["rail_scope_id"] == "c" * 64
        assert original["metadata"]["rail_from_point"] == (20.0, 110.3)
        assert original["metadata"]["rail_to_point"] == (18.3, 109.5)


def test_rail_first_research_uses_selected_train_scope_and_station_points():
    from travel_agent.planning.research.transport.rail.followup import compile_rail_followup_packet

    state = _rail_state()
    envelope = _ticket_envelope([_ticket_row(), _ticket_row("D7203")])
    original = json.loads(json.dumps(envelope))
    envelope["metadata"].update({
        "rail_selected_train": {"train_code": "D7203", "from_code": "HMQ", "to_code": "SEQ"},
        "rail_route_leg": {"leg_role": "inter_destination", "from_place_id": "city_haikou",
                           "to_place_id": "city_sanya", "service_date": "2026-10-10", "cross_day_required": False},
        "rail_scope_id": "b" * 64,
        "rail_from_point": [20.0, 110.3], "rail_to_point": [18.3, 109.5],
    })
    packet = compile_rail_followup_packet(
        state=state, catalog=state.recommendation_catalog, envelope=envelope,
        task_id="fixture", existing_candidate_ids=set(),
    )
    assert len(packet.candidates) == 1
    candidate = packet.candidates[0]
    assert candidate.segments[0].service_number == "D7203"
    assert candidate.provider_evidence_scope_id == "b" * 64
    assert (candidate.from_endpoint.latitude, candidate.from_endpoint.longitude) == (20.0, 110.3)
    assert (candidate.to_endpoint.latitude, candidate.to_endpoint.longitude) == (18.3, 109.5)
    assert packet.source_records[0].snapshot == original
    assert any(link.source_locator.startswith("sanitized_result.results[1]")
               for fact in packet.fact_assertions for link in fact.source_links)
    envelope["metadata"]["rail_route_leg"]["cross_day_required"] = True
    same_day = compile_rail_followup_packet(
        state=state, catalog=state.recommendation_catalog, envelope=envelope,
        task_id="fixture", existing_candidate_ids=set(),
    )
    assert same_day.candidates[0].provider_evidence_scope_id is None
    assert same_day.candidates[0].route_id == candidate.route_id


def test_rail_source_locators_use_cached_provider_snapshot():
    from travel_agent.planning.research.output.identifiers import _canonical_snapshot_hash
    from travel_agent.planning.research.transport.rail.followup import compile_rail_followup_packet

    state = _rail_state()
    envelope = _ticket_envelope([{"truncated": True}, _ticket_row()])
    result = envelope["sanitized_result"]
    envelope["metadata"]["snapshot_cache"] = {
        "origin": "provider_snapshot_cache", "cache_key_digest": "a" * 64,
        "content_hash": _canonical_snapshot_hash(result),
        "observed_at": "2026-10-09T00:00:00+00:00", "retrieved_at": "2026-10-09T00:00:00+00:00",
        "cache_valid_until": "2026-10-10T00:00:00+00:00", "contract_version": "1",
    }
    packet = compile_rail_followup_packet(
        state=state, catalog=state.recommendation_catalog, envelope=envelope,
        task_id="fixture", existing_candidate_ids=set(),
    )
    assert packet.source_records[0].snapshot == result
    assert packet.source_records[0].cache_provenance.origin == "provider_snapshot_cache"
    assert all(link.source_locator.startswith("results[1]") or link.source_locator == "date"
               for fact in packet.fact_assertions for link in fact.source_links)


@pytest.mark.asyncio
async def test_rail_followup_journal_restores_packets_without_requery(monkeypatch):
    from tests.support.memory_stores import InMemoryWorkerJournalStore
    from travel_agent.runtime.journal import WorkerJournal, current_worker_journal

    state = _rail_state()
    calls = []
    store = InMemoryWorkerJournalStore()
    monkeypatch.setattr(followup, "get_model_router", lambda: None)
    monkeypatch.setattr(followup, "llm_for_task", lambda *args, **kwargs: object())
    monkeypatch.setattr(followup, "get_available_tools", lambda: _available())
    monkeypatch.setattr(followup, "filter_tools_for_agent", lambda tools, agent: tools)

    async def react(**kwargs):
        calls.append(1)
        return SimpleNamespace(outcome=followup.ReactOutcome.FINAL_ANSWER, content="动车", error=None,
                               tool_results=[_ticket_envelope([_ticket_row()])])

    monkeypatch.setattr(followup, "streaming_react_loop", react)
    token = current_worker_journal.set(WorkerJournal(store, "run", "scope", 0, {}, None))
    try:
        first, catalog = await followup.research_transport_followup(
            state, question="动车", arrangement="三亚", request_id="rail-1",
            from_destination_id="city_haikou", to_destination_id="city_sanya", service_date="2026-10-10",
        )
    finally:
        current_worker_journal.reset(token)
    version, payload = await store.load("run", "scope")
    token = current_worker_journal.set(WorkerJournal(store, "run", "scope", version, payload, None))
    try:
        second, restored = await followup.research_transport_followup(
            state, question="动车", arrangement="三亚", request_id="rail-1",
            from_destination_id="city_haikou", to_destination_id="city_sanya", service_date="2026-10-10",
        )
    finally:
        current_worker_journal.reset(token)
    assert first == second
    assert restored == catalog
    assert calls == [1]
