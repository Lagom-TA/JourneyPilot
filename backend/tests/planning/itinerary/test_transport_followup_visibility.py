"""交通补查结果在组合中可见并可用于安排。"""

import json

import pytest

from tests.fixtures.itinerary import itinerary_draft, restore_planning_state
from tests.fixtures.planning_state import make_planning_state
from tests.fixtures.research_catalog import make_catalog
from travel_agent.planning.itinerary.composition import _compose_draft
from travel_agent.planning.itinerary.model_schema import _composition_response_schema
from travel_agent.planning.research.transport.followup import FOLLOWUP_TOOL_NAME
from travel_agent.tools.content import compact_tool_content_for_model
from travel_agent.tools.governance import build_tool_execution_envelope


def _response():
    return build_tool_execution_envelope(
        tool_name=FOLLOWUP_TOOL_NAME,
        arguments={},
        source="local",
        result={
            "success": True,
            "routes": [{
                "candidate_id": "candidate_train_1",
                "route_id": "12306:2026-10-10:C7875:HMQ:SEQ",
                "from_endpoint": {"name": "海口东", "station_code": "HMQ"},
                "to_endpoint": {"name": "三亚", "station_code": "SEQ"},
                "departure_at": "2026-10-10T09:20:00+08:00",
                "arrival_at": "2026-10-10T11:13:00+08:00",
                "duration_minutes": 113,
                "service_number": "C7875",
                "total_cost_cny": 119,
            }],
        },
    )


def test_compacted_transport_reply_keeps_candidate_and_train_facts():
    shown = json.loads(compact_tool_content_for_model(_response()))["sanitized_result"]["routes"][0]
    assert shown["candidate_id"] == "candidate_train_1"
    assert shown["route_id"] == "12306:2026-10-10:C7875:HMQ:SEQ"
    assert shown["from_endpoint"]["name"] == "海口东"
    assert shown["to_endpoint"]["name"] == "三亚"
    assert shown["departure_at"] == "2026-10-10T09:20:00+08:00"
    assert shown["arrival_at"] == "2026-10-10T11:13:00+08:00"
    assert shown["duration_minutes"] == 113
    assert shown["service_number"] == "C7875"
    assert shown["total_cost_cny"] == 119


def test_compacted_reply_prioritizes_routes_over_long_research_notes():
    response = _response()
    response["sanitized_result"]["research_notes"] = "研究记录" * 10000
    shown = json.loads(compact_tool_content_for_model(response))
    assert shown["sanitized_result"]["routes"][0]["candidate_id"] == "candidate_train_1"
    assert "C7875" in json.dumps(shown, ensure_ascii=False)


def test_compacted_transport_reply_keeps_candidate_when_many_routes_exceed_budget():
    response = _response()
    route = response["sanitized_result"]["routes"][0]
    response["sanitized_result"]["routes"] = [
        {
            **route,
            "candidate_id": f"candidate_train_{index}",
            "from_endpoint": {"name": "海口东" * 100, "station_code": "HMQ"},
            "to_endpoint": {"name": "三亚" * 150, "station_code": "SEQ"},
        }
        for index in range(8)
    ]
    shown = json.loads(compact_tool_content_for_model(response))["sanitized_result"]
    assert shown["routes"][0]["candidate_id"] == "candidate_train_0"
    assert shown["routes"][0]["service_number"] == "C7875"


def test_composition_schema_keeps_space_for_later_transport_candidates():
    schema = _composition_response_schema(
        make_catalog(), skeleton_only=True, strict_wire=False, dynamic_transport=True
    )
    day = schema["$defs"]["DayComposition"]
    placement = day["properties"]["placements"]["items"]
    assert placement["discriminator"]["mapping"]["transport"] == "#/$defs/TransportPlacement"
    transport = schema["$defs"]["TransportPlacement"]["properties"]
    assert transport["candidate_id"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert "authored_route" not in transport


@pytest.mark.asyncio
async def test_composition_can_select_a_candidate_returned_by_transport_followup(monkeypatch):
    from travel_agent.planning.itinerary import composition

    catalog = make_catalog()
    state = restore_planning_state(make_planning_state(), recommendation_catalog=catalog)
    response = _response()
    response["followup_packets"] = []
    seen = {}

    async def specialist(current, **kwargs):
        seen.update(kwargs)
        return response, current.recommendation_catalog

    monkeypatch.setattr(composition, "research_transport_followup", specialist)

    class Model:
        async def ainvoke_with_tools_events(self, messages, tools):
            tool_messages = [item for item in messages if item.get("role") == "tool"]
            if not tool_messages:
                prompt = str(messages[1]["content"])
                assert "交通补查返回的长途路线 candidate_id" in prompt
                yield {"type": "finish", "content": "", "tool_calls": [{
                    "id": "train-1", "name": FOLLOWUP_TOOL_NAME,
                    "arguments": {
                        "question": "海口到三亚怎么去", "current_arrangement": "上午出发",
                        "destination_id": "city_sanya", "from_destination_id": "city_haikou",
                        "to_destination_id": "city_sanya", "service_date": "2026-10-10",
                    },
                }]}
                return
            route = json.loads(tool_messages[-1]["content"])["sanitized_result"]["routes"][0]
            draft = itinerary_draft([{
                "placement_kind": "transport", "candidate_id": route["candidate_id"],
            }])
            yield {"type": "finish", "content": json.dumps(draft, ensure_ascii=False), "tool_calls": []}

    draft = await _compose_draft(state, "安排", Model(), available_tools=[], tool_context={})
    assert draft.days[0].placements[0].candidate_id == "candidate_train_1"
    assert seen["from_destination_id"] == "city_haikou"
    assert seen["to_destination_id"] == "city_sanya"
    assert seen["service_date"] == "2026-10-10"


@pytest.mark.asyncio
async def test_rail_followup_reaches_composition_and_public_itinerary(monkeypatch):
    from types import SimpleNamespace

    from travel_agent.planning.delivery.evidence_basis import EvidenceBasisView
    from travel_agent.planning.delivery.fact_projection import build_fact_snapshot, workspace_for_public_projection
    from travel_agent.planning.delivery.public.itinerary import _public_itinerary
    from travel_agent.planning.itinerary.materialize import materialize_trip_workspace
    from travel_agent.planning.research.transport import followup

    state = restore_planning_state(
        make_planning_state(),
        controlled_trip_identity={
            "start_date": "2026-10-10", "end_date": "2026-10-10",
            "destinations": [
                {"place_id": "city_haikou", "name": "海口", "country_code": "CN"},
                {"place_id": "city_sanya", "name": "三亚", "country_code": "CN"},
            ],
        },
    )
    envelope = build_tool_execution_envelope(
        tool_name="get-tickets", server_name="12306-train", source="mcp", status="success",
        arguments={"date": "2026-10-10", "fromStation": "VUQ", "toStation": "SEQ"},
        result={
            "success": True, "provider": "12306", "date": "2026-10-10",
            "from_station": "VUQ", "to_station": "SEQ",
            "results": [{
                "train_code": "C7875", "from_name": "海口东", "from_code": "HMQ",
                "to_name": "三亚", "to_code": "SEQ", "departure_time": "09:20",
                "arrival_time": "11:13", "duration_minutes": 113, "min_price_cny": 119,
            }],
        },
        audit_id="rail-audit",
    )
    envelope["metadata"]["evidence_allowed"] = True

    async def available():
        return []

    async def react(**kwargs):
        return SimpleNamespace(
            outcome=followup.ReactOutcome.FINAL_ANSWER, content="已查询车次。",
            tool_results=[envelope], error=None,
        )

    monkeypatch.setattr(followup, "get_model_router", lambda: None)
    monkeypatch.setattr(followup, "llm_for_task", lambda *args, **kwargs: object())
    monkeypatch.setattr(followup, "get_available_tools", available)
    monkeypatch.setattr(followup, "filter_tools_for_agent", lambda tools, agent: tools)
    monkeypatch.setattr(followup, "streaming_react_loop", react)

    class Model:
        async def ainvoke_with_tools_events(self, messages, tools):
            tool_messages = [item for item in messages if item.get("role") == "tool"]
            if not tool_messages:
                yield {"type": "finish", "content": "", "tool_calls": [{
                    "id": "rail-followup", "name": FOLLOWUP_TOOL_NAME,
                    "arguments": {
                        "question": "海口去三亚的动车", "current_arrangement": "10月10日上午",
                        "destination_id": "city_sanya", "from_destination_id": "city_haikou",
                        "to_destination_id": "city_sanya", "service_date": "2026-10-10",
                    },
                }]}
                return
            route = json.loads(tool_messages[-1]["content"])["sanitized_result"]["routes"][0]
            draft = itinerary_draft([{
                "placement_kind": "transport", "candidate_id": route["candidate_id"],
            }])
            draft["days"][0]["destination_id"] = "city_sanya"
            yield {"type": "finish", "content": json.dumps(draft, ensure_ascii=False), "tool_calls": []}

    updates = []
    draft = await _compose_draft(
        state, "安排海南行程", Model(), available_tools=[], tool_context={}, catalog_updates=updates,
    )
    catalog = updates[-1]
    candidate = catalog.candidate_index()[draft.days[0].placements[0].candidate_id]
    packet = next(packet for packet in catalog.research_packets if candidate in packet.candidates)
    source = next(source for source in packet.source_records if source.source_record_id in candidate.source_record_ids)
    assert source.snapshot["sanitized_result"]["results"][0]["train_code"] == "C7875"
    assert any(
        link.source_locator == "sanitized_result.results[0]"
        for fact in packet.fact_assertions if fact.entity_ref.entity_id == candidate.candidate_id
        for link in fact.source_links
    )

    workspace = materialize_trip_workspace(
        run_id=state.run_id, workspace_revision=1, composition=draft, catalog=catalog,
        requirements="海南", composition_mutations=[],
    )
    snapshot = build_fact_snapshot(workspace)
    public_workspace = workspace_for_public_projection(workspace, snapshot)
    public = _public_itinerary(public_workspace.itinerary, EvidenceBasisView.from_itinerary(workspace.itinerary))
    rail = public["transport_legs"][0]
    assert rail["from_endpoint"]["name"] == "海口东"
    assert rail["to_endpoint"]["name"] == "三亚"
    assert rail["departure_at"] == "2026-10-10T09:20:00+08:00"
    assert rail["arrival_at"] == "2026-10-10T11:13:00+08:00"
    assert rail["segments"][0]["service_number"] == "C7875"
    assert rail["total_cost_cny"] == 119
    assert public["day_plans"][0]["date"] == "2026-10-10"
    assert public["day_plans"][0]["timeline"][0]["entity_type"] == "transport_leg"
