import json

import pytest

from tests.fixtures.itinerary import itinerary_draft
from tests.fixtures.planning_state import make_planning_state
from tests.fixtures.research_catalog import make_catalog, make_local_transport_packet
from travel_agent.planning.itinerary import rail_paths
from travel_agent.planning.itinerary.materialize import materialize_trip_workspace
from travel_agent.planning.itinerary.parsing import parse_itinerary_composition
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.planning.requirements.snapshot_contracts import IntentContractSnapshot
from travel_agent.planning.transport import TransportEndpoint
from travel_agent.tools.governance import build_tool_execution_envelope


def _rail_workspace(mode="train", *, provider_name="12306"):
    packet = make_local_transport_packet(
        "candidate_rail",
        origin_place_id="12306:AOH",
        destination_place_id="12306:BJP",
    )
    origin = TransportEndpoint(
        name="上海虹桥",
        place_id="12306:AOH",
        station_code="AOH",
        latitude=31.197,
        longitude=121.327,
    )
    destination = TransportEndpoint(
        name="北京南",
        place_id="12306:BJP",
        station_code="BJP",
        latitude=39.865,
        longitude=116.379,
    )
    departure = "2026-10-10T08:00:00+08:00"
    arrival = "2026-10-10T12:00:00+08:00"
    segment = {
        "segment_id": "segment_rail",
        "mode": mode,
        "from_endpoint": origin.model_dump(mode="python"),
        "to_endpoint": destination.model_dump(mode="python"),
        "departure_at": departure,
        "arrival_at": arrival,
        "duration_minutes": 240,
        "distance_meters": None,
        "operator_name": "中国铁路",
        "service_number": "G1" if mode == "high_speed_rail" else "K1",
        "line_name": None,
        "cost_cny": 553.0,
        "path": [],
    }
    route = {
        "route_id": "route_candidate_rail",
        "transport_class": "long_distance",
        "selected_mode": mode,
        "from_endpoint": origin.model_dump(mode="python"),
        "to_endpoint": destination.model_dump(mode="python"),
        "departure_at": departure,
        "arrival_at": arrival,
        "duration_minutes": 240,
        "distance_meters": None,
        "total_cost_cny": 553.0,
        "segments": [segment],
        "booking_status": "not_required",
    }
    payload = packet.model_dump(mode="python")
    candidate = payload["candidates"][0]
    candidate.update(
        transport_class="long_distance",
        provider_evidence_scope_id="a" * 64,
        selected_mode=mode,
        from_endpoint=origin.model_dump(mode="python"),
        to_endpoint=destination.model_dump(mode="python"),
        departure_at=departure,
        arrival_at=arrival,
        duration_minutes=240,
        total_cost_cny=553.0,
        segments=[segment],
    )
    payload["source_records"][0].update(
        provider_name=provider_name,
        title="12306 train route",
        snapshot={
            "tool_name": "domestic_rail_search",
            "server_name": "12306-train",
            "sanitized_result": {
                "success": True,
                "provider": "12306",
                "routes": [route],
            },
        },
    )
    rail_packet = ResearchPacket.model_validate(payload)
    catalog = make_catalog(rail_packet)
    skeleton = parse_itinerary_composition(
        json.dumps(
            itinerary_draft(
                [{"placement_kind": "transport", "candidate_id": "candidate_rail"}]
            )
        )
    )
    state = make_planning_state()
    return materialize_trip_workspace(
        run_id=state.run_id,
        workspace_revision=0,
        composition=skeleton,
        catalog=catalog,
        intent_contract_snapshot=IntentContractSnapshot.from_intent_spec(
            state.intent_spec
        ),
        composition_mutations=[],
    )


def _allow_route_tool(monkeypatch, *, available=True):
    class Registry:
        def has_tool(self, name):
            return available and name == "global_route_search"

    monkeypatch.setattr(rail_paths, "get_tool_registry", lambda: Registry())


def _route_envelope(arguments, *, mode, path):
    def endpoint(prefix):
        return {
            "name": arguments[f"{prefix}_name"],
            "place_id": arguments[f"{prefix}_place_id"],
            "latitude": arguments[f"{prefix}_latitude"],
            "longitude": arguments[f"{prefix}_longitude"],
        }

    origin = endpoint("from")
    destination = endpoint("to")
    result = {
        "success": True,
        "provider": "transitous",
        "retrieved_at": "2026-10-26T00:00:00+00:00",
        "request": arguments,
        "routes": [
            {
                "route_id": f"geometry:{mode}",
                "provider": "transitous",
                "transport_class": "public_transit",
                "selected_mode": mode,
                "from_endpoint": origin,
                "to_endpoint": destination,
                "departure_at": None,
                "arrival_at": None,
                "duration_minutes": 240,
                "distance_meters": None,
                "total_cost_cny": None,
                "segments": [
                    {
                        "segment_id": "geometry_segment",
                        "mode": mode,
                        "from_endpoint": origin,
                        "to_endpoint": destination,
                        "departure_at": None,
                        "arrival_at": None,
                        "duration_minutes": 240,
                        "distance_meters": None,
                        "operator_name": None,
                        "service_number": None,
                        "line_name": None,
                        "cost_cny": None,
                        "path": path,
                    }
                ],
                "booking_status": "not_required",
            }
        ],
        "provider_response": {"mocked": True},
    }
    envelope = build_tool_execution_envelope(
        tool_name="global_route_search",
        arguments=arguments,
        result=result,
        status="success",
        source="builtin",
        server_name="route_search",
        category="data",
        audit_id="audit_rail_path",
        retrieved_at="2026-10-26T00:00:00+00:00",
    )
    envelope["metadata"]["evidence_allowed"] = True
    return envelope


def _geometry_path():
    return [
        {"latitude": 31.197, "longitude": 121.327},
        {"latitude": 32.0, "longitude": 120.0},
        {"latitude": 39.865, "longitude": 116.379},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["train", "high_speed_rail"])
async def test_12306_rail_accepts_only_matching_geometry_without_changing_facts(
    monkeypatch, mode
):
    workspace = _rail_workspace(mode)
    original_leg = workspace.itinerary.transport_legs[0]
    calls = []
    _allow_route_tool(monkeypatch)

    async def execute(tool_name, arguments, **kwargs):
        calls.append((tool_name, arguments, kwargs))
        return _route_envelope(arguments, mode=mode, path=_geometry_path())

    monkeypatch.setattr(rail_paths, "execute_tool", execute)
    audit_store = object()
    completed = await rail_paths.complete_rail_route_paths(
        workspace,
        tool_context={"run_id": "run_test", "tool_audit_store": audit_store},
    )

    leg = completed.itinerary.transport_legs[0]
    assert [point.model_dump() for point in leg.segments[0].path] == _geometry_path()
    assert leg.selected_mode == original_leg.selected_mode
    assert leg.departure_at == original_leg.departure_at
    assert leg.arrival_at == original_leg.arrival_at
    assert leg.total_cost_cny == original_leg.total_cost_cny
    assert leg.from_endpoint == original_leg.from_endpoint
    assert leg.to_endpoint == original_leg.to_endpoint
    assert leg.segments[0].service_number == original_leg.segments[0].service_number
    assert completed.recommendation_catalog == workspace.recommendation_catalog
    candidate = completed.recommendation_catalog.candidate_index()["candidate_rail"]
    assert candidate.segments[0].path == []
    assert len(calls) == 1
    tool_name, arguments, kwargs = calls[0]
    assert tool_name == "global_route_search"
    assert arguments["mode"] == "public_transit"
    assert arguments["departure_time"] == original_leg.departure_at.isoformat()
    assert kwargs["allowed_tool_names"] == {"global_route_search"}
    assert kwargs["max_retries"] == 0
    assert kwargs["activation_source"] == "rail_route_path_completion"
    assert kwargs["allow_fallback"] is False
    assert kwargs["tool_audit_store"] is audit_store

    repeated = await rail_paths.complete_rail_route_paths(completed)
    assert repeated is completed
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target_mode", "provider_mode"),
    [
        ("train", "bus"),
        ("train", "drive"),
        ("train", "walk"),
        ("train", "high_speed_rail"),
        ("high_speed_rail", "train"),
    ],
)
async def test_12306_rail_rejects_non_rail_and_mismatched_geometry(
    monkeypatch, target_mode, provider_mode
):
    workspace = _rail_workspace(target_mode)
    _allow_route_tool(monkeypatch)

    async def execute(tool_name, arguments, **kwargs):
        return _route_envelope(
            arguments, mode=provider_mode, path=_geometry_path()
        )

    monkeypatch.setattr(rail_paths, "execute_tool", execute)
    completed = await rail_paths.complete_rail_route_paths(workspace)

    assert completed is workspace
    assert completed.itinerary.transport_legs[0].segments[0].path == []


@pytest.mark.asyncio
async def test_12306_rail_keeps_empty_path_when_provider_has_no_geometry(monkeypatch):
    workspace = _rail_workspace("train")
    _allow_route_tool(monkeypatch)

    async def execute(tool_name, arguments, **kwargs):
        return _route_envelope(arguments, mode="train", path=[])

    monkeypatch.setattr(rail_paths, "execute_tool", execute)
    completed = await rail_paths.complete_rail_route_paths(workspace)

    assert completed is workspace
    assert completed.itinerary.transport_legs[0].segments[0].path == []


@pytest.mark.asyncio
async def test_12306_rail_tool_unavailable_or_exception_preserves_delivery(monkeypatch):
    workspace = _rail_workspace("train")
    _allow_route_tool(monkeypatch, available=False)

    async def no_query(*args, **kwargs):
        pytest.fail("路线工具未注册时不能执行查询")

    monkeypatch.setattr(rail_paths, "execute_tool", no_query)
    unavailable = await rail_paths.complete_rail_route_paths(workspace)
    assert unavailable is workspace

    _allow_route_tool(monkeypatch)

    async def fail(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(rail_paths, "execute_tool", fail)
    failed = await rail_paths.complete_rail_route_paths(workspace)
    assert failed is workspace
    assert failed.itinerary.transport_legs[0].segments[0].path == []
