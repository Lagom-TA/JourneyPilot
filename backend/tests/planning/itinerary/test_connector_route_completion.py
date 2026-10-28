import json

import pytest

from tests.fixtures.itinerary import (
    itinerary_draft,
    restore_planning_state,
    visit_entry,
)
from tests.fixtures.planning_state import make_planning_state
from tests.fixtures.research_catalog import make_catalog, make_visit_packet
from travel_agent.planning.itinerary import node
from travel_agent.planning.itinerary.draft import AuthoredRoute
from travel_agent.planning.itinerary.parsing import parse_itinerary_composition
from travel_agent.planning.research.candidates import TransportCandidate
from travel_agent.planning.research.discovery_contracts import CandidateDiscoveryOrigin
from travel_agent.planning.research.transport import local_routes
from travel_agent.tools.governance import build_tool_execution_envelope


@pytest.fixture(autouse=True)
def _mock_composition_model(monkeypatch):
    monkeypatch.setattr(node, "get_model_router", lambda: None)
    monkeypatch.setattr(node, "llm_for_task", lambda *args, **kwargs: object())


def _located_visit(candidate_id, *, located=True):
    packet = make_visit_packet(
        candidate_id,
        candidate_id,
        origin=CandidateDiscoveryOrigin.INTENT_QUERY,
        query_id=f"query_{candidate_id}",
        intent_id="intent_test",
    )
    if not located:
        return packet
    source = packet.source_records[0].model_copy(
        update={
            "snapshot": {
                "results": [
                    {
                        "place_id": f"place_{candidate_id}",
                        "latitude": 35.6,
                        "longitude": 139.7,
                    }
                ]
            }
        }
    )
    return packet.model_copy(update={"source_records": [source]})


def _planning_state(*, stop_count=2, unlocated_stop=None, constraint_pack=None):
    packets = [
        _located_visit(
            f"candidate_{index}", located=index != unlocated_stop
        )
        for index in range(stop_count)
    ]
    times = (("08:00", "09:00"), ("09:10", "10:10"), ("10:20", "11:20"))
    placements = []
    for index, (start, end) in enumerate(times[:stop_count]):
        placement = visit_entry(start, end)
        placement["candidate_id"] = f"candidate_{index}"
        placements.append(placement)
    skeleton = parse_itinerary_composition(
        json.dumps(itinerary_draft(placements))
    )
    current = make_planning_state()
    if constraint_pack is not None:
        current = restore_planning_state(current, constraint_pack=constraint_pack)
    return restore_planning_state(
        current,
        recommendation_catalog=make_catalog(*packets),
        placement_skeleton=skeleton,
        execution_plan=[["itinerary_planner"]],
        agent_status={"itinerary_planner": "pending"},
    )


def _envelope(result, arguments, *, audit_id="audit_connector_test"):
    envelope = build_tool_execution_envelope(
        tool_name="global_route_search",
        arguments=arguments,
        result=result,
        status="success",
        source="builtin",
        server_name="route_search",
        category="data",
        audit_id=audit_id,
        retrieved_at="2026-10-26T00:00:00+00:00",
    )
    envelope["metadata"]["evidence_allowed"] = True
    return envelope


def _route_result(
    request,
    *,
    path_point_count=2,
    selected_mode="metro",
    transport_class="public_transit",
):
    def endpoint(prefix):
        return {
            "name": request[f"{prefix}_name"],
            "place_id": request[f"{prefix}_place_id"],
            "latitude": request[f"{prefix}_latitude"],
            "longitude": request[f"{prefix}_longitude"],
        }

    origin = endpoint("from")
    destination = endpoint("to")
    path = [
        {
            "latitude": origin["latitude"] + index * 0.0001,
            "longitude": origin["longitude"] + index * 0.0001,
        }
        for index in range(path_point_count)
    ]
    route_id = (
        f"route:{origin['place_id']}:{destination['place_id']}:{selected_mode}"
    )
    segment = {
        "segment_id": "segment_1",
        "mode": selected_mode,
        "from_endpoint": origin,
        "to_endpoint": destination,
        "departure_at": None,
        "arrival_at": None,
        "duration_minutes": 12,
        "distance_meters": 1200,
        "operator_name": None,
        "service_number": "M1",
        "line_name": "Mock Metro",
        "cost_cny": None,
        "path": path,
    }
    return {
        "success": True,
        "provider": "transitous",
        "retrieved_at": "2026-10-26T00:00:00+00:00",
        "request": request,
        "routes": [
            {
                "route_id": route_id,
                "provider": "transitous",
                "transport_class": transport_class,
                "selected_mode": selected_mode,
                "from_endpoint": origin,
                "to_endpoint": destination,
                "departure_at": None,
                "arrival_at": None,
                "duration_minutes": 12,
                "distance_meters": 1200,
                "total_cost_cny": None,
                "segments": [segment],
                "booking_status": "not_required",
            }
        ],
        "provider_response": {"mocked": True},
    }


def _allow_route_tool(monkeypatch):
    class Registry:
        def has_tool(self, name):
            return name == "global_route_search"

    monkeypatch.setattr(local_routes, "get_tool_registry", lambda: Registry())


def _locked_mode_pack(mode):
    return {
        "hard_constraints": [
            {
                "status": "active",
                "visibility": "user_visible",
                "category": "transport_constraint",
                "source_refs": [{"source": "current_query"}],
                "params": {"locked_local_mode": mode},
            }
        ],
        "soft_preferences": [],
    }


def _authored_routes(gaps, *, duration=17):
    return {
        gap.gap_id: AuthoredRoute(
            mode="walk",
            duration_minutes=duration,
            selection_reason="Provider 无可用结果，保留估算",
        )
        for gap in gaps
    }


async def _complete(current):
    return restore_planning_state(
        current, **await node.itinerary_planner_node(current, {})
    )


@pytest.mark.asyncio
async def test_routable_unfilled_gap_uses_provider_route_without_estimation(
    monkeypatch,
):
    current = _planning_state()
    calls = []
    _allow_route_tool(monkeypatch)

    async def execute(tool_name, arguments, **kwargs):
        calls.append((tool_name, arguments, kwargs))
        return _envelope(_route_result(arguments), arguments)

    async def no_estimation(*args, **kwargs):
        pytest.fail("a routable Provider result must not be replaced by an estimate")

    monkeypatch.setattr(local_routes, "execute_tool", execute)
    monkeypatch.setattr(node, "_author_connector_routes", no_estimation)

    completed = await _complete(current)

    assert completed.agent_status["itinerary_planner"] == "completed"
    assert len(calls) == 1
    leg = completed.trip_workspace_v2.itinerary.transport_legs[0]
    candidate = completed.recommendation_catalog.candidate_index()[
        leg.lineage.candidate_id
    ]
    assert isinstance(candidate, TransportCandidate)
    assert leg.duration_minutes == 12
    assert leg.lineage.lineage_kind == "candidate_entity"
    source = next(
        source
        for packet in completed.recommendation_catalog.research_packets
        for source in packet.source_records
        if source.source_record_id in candidate.source_record_ids
    )
    assert source.tool_audit_id == "audit_connector_test"
    assert any(
        fact.field_path == "segments"
        for packet in completed.recommendation_catalog.research_packets
        for fact in packet.fact_assertions
        if fact.entity_ref.entity_id == candidate.candidate_id
    )


@pytest.mark.asyncio
async def test_provider_without_a_route_still_uses_estimation(monkeypatch):
    current = _planning_state()
    authored_gap_ids = []
    _allow_route_tool(monkeypatch)

    async def execute(tool_name, arguments, **kwargs):
        result = {
            "success": True,
            "provider": "transitous",
            "routes": [],
            "retrieved_at": "2026-10-26T00:00:00+00:00",
        }
        return _envelope(result, arguments)

    async def author(_llm, gaps):
        authored_gap_ids.extend(gap.gap_id for gap in gaps)
        return _authored_routes(gaps)

    monkeypatch.setattr(local_routes, "execute_tool", execute)
    monkeypatch.setattr(node, "_author_connector_routes", author)

    completed = await _complete(current)

    assert completed.agent_status["itinerary_planner"] == "completed"
    assert authored_gap_ids == [
        gap.gap_id for gap in completed.local_connector_gaps
    ]
    leg = completed.trip_workspace_v2.itinerary.transport_legs[0]
    assert leg.duration_minutes == 17
    assert leg.lineage.lineage_kind == "authored_entity"
    assert leg.segments[0].path == []


@pytest.mark.asyncio
@pytest.mark.parametrize("unlocated_stop", [0, 1])
async def test_missing_coordinates_never_queries_provider(
    monkeypatch, unlocated_stop
):
    current = _planning_state(unlocated_stop=unlocated_stop)
    authored_gap_ids = []
    _allow_route_tool(monkeypatch)

    async def no_query(*args, **kwargs):
        pytest.fail("a gap without two located endpoints must not be queried")

    async def author(_llm, gaps):
        authored_gap_ids.extend(gap.gap_id for gap in gaps)
        return _authored_routes(gaps)

    monkeypatch.setattr(local_routes, "execute_tool", no_query)
    monkeypatch.setattr(node, "_author_connector_routes", author)

    completed = await _complete(current)

    assert completed.agent_status["itinerary_planner"] == "completed"
    assert len(authored_gap_ids) == 1
    assert completed.trip_workspace_v2.itinerary.transport_legs[0].duration_minutes == 17


@pytest.mark.asyncio
async def test_each_unfilled_gap_is_queried_once_without_tool_retries(monkeypatch):
    current = _planning_state(stop_count=3)
    calls = []
    _allow_route_tool(monkeypatch)

    async def execute(tool_name, arguments, **kwargs):
        calls.append((tool_name, arguments, kwargs))
        return _envelope(
            {
                "success": True,
                "provider": "transitous",
                "routes": [],
                "retrieved_at": "2026-10-26T00:00:00+00:00",
            },
            arguments,
            audit_id=f"audit_connector_{len(calls)}",
        )

    async def author(_llm, gaps):
        return _authored_routes(gaps)

    monkeypatch.setattr(local_routes, "execute_tool", execute)
    monkeypatch.setattr(node, "_author_connector_routes", author)

    completed = await _complete(current)

    assert completed.agent_status["itinerary_planner"] == "completed"
    assert len(calls) == 2
    pairs = {
        (arguments["from_place_id"], arguments["to_place_id"])
        for _, arguments, _ in calls
    }
    assert pairs == {
        ("place_candidate_0", "place_candidate_1"),
        ("place_candidate_1", "place_candidate_2"),
    }
    assert all(kwargs["max_retries"] == 0 for _, _, kwargs in calls)
    assert all(
        kwargs["activation_source"] == "local_connector_route_completion"
        for _, _, kwargs in calls
    )


@pytest.mark.asyncio
async def test_selected_provider_route_preserves_complete_path(monkeypatch):
    current = _planning_state()
    _allow_route_tool(monkeypatch)

    async def execute(tool_name, arguments, **kwargs):
        return _envelope(_route_result(arguments, path_point_count=8), arguments)

    async def no_estimation(*args, **kwargs):
        pytest.fail("the Provider route with geometry must be selected")

    monkeypatch.setattr(local_routes, "execute_tool", execute)
    monkeypatch.setattr(node, "_author_connector_routes", no_estimation)

    completed = await _complete(current)

    leg = completed.trip_workspace_v2.itinerary.transport_legs[0]
    actual_path = [point.model_dump() for point in leg.segments[0].path]
    expected_path = _route_result(
        {
            "from_name": "candidate_0",
            "from_place_id": "place_candidate_0",
            "from_latitude": 35.6,
            "from_longitude": 139.7,
            "to_name": "candidate_1",
            "to_place_id": "place_candidate_1",
            "to_latitude": 35.6,
            "to_longitude": 139.7,
        },
        path_point_count=8,
    )["routes"][0]["segments"][0]["path"]
    assert actual_path == expected_path
    candidate = completed.recommendation_catalog.candidate_index()[
        leg.lineage.candidate_id
    ]
    assert [point.model_dump() for point in candidate.segments[0].path] == expected_path


@pytest.mark.asyncio
@pytest.mark.parametrize("requested_mode", ["taxi", "ride_hailing"])
async def test_road_service_modes_query_drive_and_keep_display_lock_and_path(
    monkeypatch, requested_mode
):
    current = _planning_state(constraint_pack=_locked_mode_pack(requested_mode))
    calls = []
    _allow_route_tool(monkeypatch)

    async def execute(tool_name, arguments, **kwargs):
        calls.append((tool_name, arguments, kwargs))
        return _envelope(
            _route_result(
                arguments,
                path_point_count=6,
                selected_mode="drive",
                transport_class="flexible",
            ),
            arguments,
        )

    async def no_estimation(*args, **kwargs):
        pytest.fail("兼容的 drive 道路路线必须满足出租车或网约车接驳")

    monkeypatch.setattr(local_routes, "execute_tool", execute)
    monkeypatch.setattr(node, "_author_connector_routes", no_estimation)

    completed = await _complete(current)

    assert completed.agent_status["itinerary_planner"] == "completed"
    assert len(calls) == 1
    assert calls[0][1]["mode"] == "drive"
    leg = completed.trip_workspace_v2.itinerary.transport_legs[0]
    assert leg.selected_mode.value == requested_mode
    assert leg.mode_preference.locked_mode.value == requested_mode
    assert leg.segments[0].mode.value == "drive"
    assert len(leg.segments[0].path) == 6
    candidate = completed.recommendation_catalog.candidate_index()[
        leg.lineage.candidate_id
    ]
    assert candidate.selected_mode.value == "drive"
    assert candidate.segments[0].mode.value == "drive"
    assert [point.model_dump() for point in candidate.segments[0].path] == [
        point.model_dump() for point in leg.segments[0].path
    ]
