import pytest

from tests.fixtures.itinerary import itinerary_draft, restore_planning_state, visit_entry
from tests.fixtures.planning_state import make_planning_state
from tests.fixtures.research_catalog import make_catalog, make_visit_packet
from travel_agent.planning.itinerary import node
from travel_agent.planning.itinerary.draft import ItineraryCompositionDraft
from travel_agent.planning.itinerary.connectors import (
    connector_mode_requests_from_constraint_pack,
    extract_local_connector_gaps,
    materialize_skeleton_connectors,
)
from travel_agent.planning.delivery.evidence_basis import EvidenceBasisView
from travel_agent.planning.delivery.public.itinerary import _public_itinerary
from travel_agent.planning.itinerary.models import TransportLeg
from travel_agent.planning.research.transport import local_routes
from travel_agent.tools.governance import build_tool_execution_envelope


def _state():
    packets = [make_visit_packet(f"visit_{index}", f"地点{index}") for index in (1, 2)]
    placements = []
    for index, (start, end) in enumerate((("08:00", "09:00"), ("09:40", "10:40")), 1):
        entry = visit_entry(start, end)
        entry["candidate_id"] = f"visit_{index}"
        placements.append(entry)
    return restore_planning_state(
        make_planning_state(), recommendation_catalog=make_catalog(*packets),
        placement_skeleton=ItineraryCompositionDraft.model_validate(itinerary_draft(placements)),
        execution_plan=[["itinerary_planner"]], agent_status={"itinerary_planner": "pending"},
    )


@pytest.mark.asyncio
async def test_transport_followup_keeps_station_and_path_facts(monkeypatch):
    state = _state()
    monkeypatch.setattr(node, "get_model_router", lambda: None)
    monkeypatch.setattr(node, "llm_for_task", lambda *args, **kwargs: object())

    async def research(current, *, gaps, **kwargs):
        gap = gaps[0]
        origin = {"name": "地点1", "place_id": gap.from_place_id}
        destination = {"name": "地点2", "place_id": gap.to_place_id}
        route = {
            "route_id": "route-1", "transport_class": "public_transit", "selected_mode": "metro",
            "from_endpoint": origin, "to_endpoint": destination, "duration_minutes": 12,
            "boarding_stop": {"name": "出发站"}, "alighting_stop": {"name": "到达站"},
            "segments": [{
                "segment_id": "segment-1", "mode": "metro", "from_endpoint": origin,
                "to_endpoint": destination, "duration_minutes": 12,
                "path": [{"latitude": 35.6, "longitude": 139.7}, {"latitude": 35.7, "longitude": 139.8}],
            }],
        }
        envelope = build_tool_execution_envelope(
            tool_name="global_route_search", arguments={}, source="builtin", audit_id="audit-route",
            result={"success": True, "provider": "fixture", "routes": [route]},
        )
        envelope["metadata"]["evidence_allowed"] = True
        packet = local_routes._route_packet(
            state=current, catalog=current.recommendation_catalog, gap=gap,
            envelope=envelope, existing_candidate_ids=set(current.recommendation_catalog.candidate_index()),
        )
        catalog = current.recommendation_catalog.model_copy(update={
            "research_packets": [*current.recommendation_catalog.research_packets, packet],
        })
        return {"status": "success"}, catalog

    monkeypatch.setattr(node, "research_transport_followup", research)
    result = await node.itinerary_planner_node(state, {})
    workspace = result["trip_workspace"]
    leg = workspace.itinerary.transport_legs[0]
    assert leg.boarding_stop.name == "出发站"
    assert leg.alighting_stop.name == "到达站"
    assert len(leg.segments[0].path) == 2
    assert leg.lineage.source_record_ids
    public = _public_itinerary(
        workspace.itinerary,
        EvidenceBasisView.from_itinerary(workspace.itinerary),
    )
    assert public["transport_legs"][0]["boarding_stop"]["name"] == "出发站"
    assert public["transport_legs"][0]["alighting_stop"]["name"] == "到达站"
    assert TransportLeg.model_validate(leg.model_dump()).alighting_stop.name == "到达站"
    candidate = result["recommendation_catalog"].candidate_index()[leg.lineage.candidate_id]
    assert candidate.boarding_stop.name == "出发站"
    assert candidate.alighting_stop.name == "到达站"
    assert candidate.segments[0].path == leg.segments[0].path


@pytest.mark.parametrize("mode", ["taxi", "ride_hailing"])
def test_verified_road_route_keeps_requested_display_mode(mode):
    state = _state()
    constraints = {
        "hard_constraints": [{
            "status": "active", "visibility": "user_visible", "category": "transport_constraint",
            "source_refs": [{"source": "current_query"}], "params": {"locked_local_mode": mode},
        }],
        "soft_preferences": [],
    }
    requests, required = connector_mode_requests_from_constraint_pack(
        state.placement_skeleton, constraints, state.recommendation_catalog
    )
    gaps = extract_local_connector_gaps(
        state.placement_skeleton, state.recommendation_catalog, weather_data_revision=0,
        flexible_mode_requests=requests, required_flexible_mode_pairs=required,
    )
    gap = gaps[0]
    origin = {"name": "地点1", "place_id": gap.from_place_id}
    destination = {"name": "地点2", "place_id": gap.to_place_id}
    route = {
        "route_id": "road-1", "transport_class": "flexible", "selected_mode": "drive",
        "from_endpoint": origin, "to_endpoint": destination, "duration_minutes": 12,
        "segments": [{"segment_id": "road-segment", "mode": "drive", "from_endpoint": origin,
                      "to_endpoint": destination, "duration_minutes": 12}],
    }
    envelope = build_tool_execution_envelope(
        tool_name="global_route_search", arguments={}, source="builtin", audit_id="audit-road",
        result={"success": True, "provider": "fixture", "routes": [route]},
    )
    envelope["metadata"]["evidence_allowed"] = True
    packet = local_routes._route_packet(
        state=state, catalog=state.recommendation_catalog, gap=gap, envelope=envelope,
        existing_candidate_ids=set(state.recommendation_catalog.candidate_index()),
    )
    catalog = state.recommendation_catalog.model_copy(update={
        "research_packets": [*state.recommendation_catalog.research_packets, packet],
    })
    draft = materialize_skeleton_connectors(state.placement_skeleton, catalog, gaps, {})
    from travel_agent.planning.itinerary.materialize import materialize_trip_workspace

    workspace = materialize_trip_workspace(
        run_id=state.run_id, workspace_revision=0, composition=draft, catalog=catalog,
        requirements=state.current_requirements, composition_mutations=[], connector_gaps=gaps,
    )
    leg = workspace.itinerary.transport_legs[0]
    assert leg.selected_mode.value == mode
    assert leg.mode_preference.locked_mode.value == mode
    assert leg.segments[0].mode.value == "drive"
