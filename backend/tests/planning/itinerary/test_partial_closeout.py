from datetime import date, datetime, timedelta

from tests.fixtures.research_catalog import (
    make_catalog,
    make_local_transport_packet,
    make_visit_packet,
)
from travel_agent.planning.itinerary.connectors import (
    LocalConnectorGap,
    extract_local_connector_gaps,
    overtimed_connector_gaps,
)
from travel_agent.planning.itinerary.day_design import apply_day_design
from travel_agent.planning.itinerary.draft import ItineraryCompositionDraft
from travel_agent.planning.itinerary.materialize import materialize_trip_workspace
from travel_agent.planning.itinerary.partial_closeout import build_partial_closeout
from travel_agent.planning.research.candidates import LodgingCandidate
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.planning.transport import TransportEndpoint


START = date(2026, 10, 10)


def _day(number, *placements, design=None):
    return {
        "day_id": f"day_{number}",
        "day": number,
        "date": START + timedelta(days=number - 1),
        "destination_id": "destination_tokyo",
        "placements": list(placements),
        "day_design": design,
    }


def _visit(candidate_id, number, start="09:00", end="10:00"):
    day = START + timedelta(days=number - 1)
    return {
        "placement_kind": "visit",
        "candidate_id": candidate_id,
        "planned_start": f"{day}T{start}:00+09:00",
        "planned_end": f"{day}T{end}:00+09:00",
        "duration_minutes": 60,
    }


def _draft(*days, lodging=()):
    return ItineraryCompositionDraft.model_validate({
        "itinerary_id": "itinerary_test",
        "title": "东京行程",
        "duration_days": len(days),
        "days": list(days),
        "lodging_candidate_ids": list(lodging),
    })


def _gap(number, name="甲", other="乙", window=10):
    day = START + timedelta(days=number - 1)
    departure = datetime.fromisoformat(f"{day}T10:00:00+09:00")
    return LocalConnectorGap(
        gap_id=f"gap_{number}_{name}",
        day_id=f"day_{number}",
        day_date=day,
        destination_id="destination_tokyo",
        from_entry_key=f"from_{name}",
        to_entry_key=f"to_{other}",
        from_place_id=f"place_{name}",
        to_place_id=f"place_{other}",
        from_endpoint=TransportEndpoint(name=name, place_id=f"place_{name}"),
        to_endpoint=TransportEndpoint(name=other, place_id=f"place_{other}"),
        departure_time=departure,
        latest_arrival_time=departure + timedelta(minutes=window),
        allowed_transport_classes=["public_transit"],
        preferred_transport_class="public_transit",
        weather_data_revision=0,
    )


def _free_time(number):
    day = START + timedelta(days=number - 1)
    return {
        "planned_start": f"{day}T15:00:00+09:00",
        "planned_end": f"{day}T16:00:00+09:00",
    }


def _night_packet(candidate_id, departure_day, arrival_day):
    packet = make_local_transport_packet(
        candidate_id, origin_place_id=f"origin_{candidate_id}",
        destination_place_id=f"destination_{candidate_id}",
    )
    payload = packet.model_dump()
    payload["candidates"][0].update({
        "transport_class": "long_distance",
        "departure_at": f"{START + timedelta(days=departure_day - 1)}T23:00:00+09:00",
        "arrival_at": f"{START + timedelta(days=arrival_day - 1)}T06:00:00+09:00",
    })
    return ResearchPacket.model_validate(payload)


def _hotel_packet(candidate_id, check_in, check_out):
    packet = make_visit_packet(candidate_id, candidate_id)
    original = packet.candidates[0].model_dump()
    candidate = {key: value for key, value in original.items() if key in LodgingCandidate.model_fields}
    candidate.update({
        "candidate_kind": "lodging",
        "property_name": candidate_id,
        "check_in_date": START + timedelta(days=check_in - 1),
        "check_out_date": START + timedelta(days=check_out - 1),
        "nights": check_out - check_in,
        "availability_status": "needs_confirmation",
    })
    payload = packet.model_dump()
    payload.update(worker_kind="accommodation_researcher", candidates=[candidate])
    return ResearchPacket.model_validate(payload)


def _workspace(draft, catalog):
    workspace = materialize_trip_workspace(
        run_id="run_test", workspace_revision=0, composition=draft, catalog=catalog,
        requirements="东京行程", composition_mutations=[],
    )
    return apply_day_design(workspace, draft)


def test_actual_overtime_clears_single_day_and_preserves_inputs():
    catalog = make_catalog(
        make_visit_packet("a", "博物馆"), make_visit_packet("b", "公园"),
        make_local_transport_packet("bus", origin_place_id="place_a", destination_place_id="place_b"),
    )
    skeleton = _draft(_day(
        1, _visit("a", 1), _visit("b", 1, "10:10", "11:10"),
        design={"free_time": [_free_time(1)], "unresolved": ["预约待确认", "预约待确认"]},
    ))
    gaps = extract_local_connector_gaps(skeleton, catalog, weather_data_revision=0)
    conflicts = overtimed_connector_gaps(catalog, gaps, {})
    original = skeleton.model_dump()
    catalog_original = catalog.model_dump()
    conflict_original = [gap.model_dump() for gap, _, _ in conflicts]

    result = build_partial_closeout(skeleton, catalog, conflicts)
    assert result.days[0].placements == []
    assert result.days[0].day_design.free_time == []
    assert result.days[0].day_design.unresolved[0] == "预约待确认"
    message = result.days[0].day_design.unresolved[1]
    assert all(value in message for value in ("尚未安排", "2026-10-10", "博物馆", "公园", "20分钟", "10分钟"))
    assert len(result.days[0].day_design.unresolved) == 2
    assert skeleton.model_dump() == original
    assert catalog.model_dump() == catalog_original
    assert [gap.model_dump() for gap, _, _ in conflicts] == conflict_original
    assert ItineraryCompositionDraft.model_validate(result.model_dump()) == result
    workspace = _workspace(result, catalog)
    assert not workspace.itinerary.day_plans[0].timeline
    assert not workspace.itinerary.visit_stops
    assert not workspace.itinerary.transport_legs
    assert not workspace.itinerary.custom_blocks
    assert not workspace.selection_slots


def test_multiple_conflicts_preserve_eight_unresolved_and_describe_negative_window():
    existing = [f"原有未决事项{index}" for index in range(8)]
    skeleton = _draft(
        _day(1, _visit("a", 1), design={"unresolved": existing, "free_time": []}),
        _day(2, _visit("b", 2)),
        _day(3, _visit("c", 3)),
    )
    catalog = make_catalog(*(make_visit_packet(value, value) for value in "abc"))
    conflicts = [
        (_gap(1, "故宫", "机场", -15), 35, -15),
        (_gap(1, "公园", "车站", 0), 12, 0),
        (_gap(1, "公园", "车站", 0), 12, 0),
        (_gap(3, "商场", "剧院", 5), 22, 5),
    ]
    result = build_partial_closeout(skeleton, catalog, conflicts)
    unresolved = result.days[0].day_design.unresolved
    assert len(unresolved) == 8
    assert all(item in "\n".join(unresolved) for item in existing)
    assert all(item in unresolved[-1] for item in (
        "2026-10-10", "故宫", "机场", "35分钟", "-15分钟", "晚15分钟", "公园", "车站", "12分钟", "0分钟",
    ))
    assert unresolved[-1].count("公园至车站") == 1
    assert result.days[1] == skeleton.days[1]
    assert result.days[2].placements == []
    assert "2026-10-12" in result.days[2].day_design.unresolved[0]
    assert skeleton.days[0].day_design.unresolved == existing


def test_cross_night_propagates_transitively_but_not_via_lodging():
    night1, night2 = _night_packet("night1", 1, 2), _night_packet("night2", 2, 3)
    bad_hotel, good_hotel = _hotel_packet("bad_hotel", 1, 3), _hotel_packet("good_hotel", 4, 5)
    packets = [night1, night2, bad_hotel, good_hotel]
    packets.extend(make_visit_packet(f"v{index}", f"景点{index}") for index in range(1, 6))
    catalog = make_catalog(*packets)
    def transport(candidate_id):
        return {"placement_kind": "transport", "candidate_id": candidate_id}

    skeleton = _draft(
        _day(1, _visit("v1", 1), transport("night1")),
        _day(2, transport("night1"), _visit("v2", 2), transport("night2")),
        _day(3, _visit("v3", 3)),
        _day(4, _visit("v4", 4), design={"free_time": [_free_time(1), _free_time(4)], "unresolved": []}),
        _day(5, _visit("v5", 5)),
        lodging=["bad_hotel", "good_hotel"],
    )
    before = skeleton.model_dump()
    result = build_partial_closeout(skeleton, catalog, [(_gap(1), 30, 10)])
    assert all(not day.placements for day in result.days[:3])
    assert all("尚未安排" in day.day_design.unresolved[0] for day in result.days[:3])
    assert result.days[3].placements == skeleton.days[3].placements
    assert result.days[4] == skeleton.days[4]
    assert result.lodging_candidate_ids == ["good_hotel"]
    assert len(result.days[3].day_design.free_time) == 1
    assert skeleton.model_dump() == before
    workspace = _workspace(result, catalog)
    assert all(not day.timeline for day in workspace.itinerary.day_plans[:3])
    assert not workspace.itinerary.transport_legs
    assert {stop.name for stop in workspace.itinerary.visit_stops} == {"景点4", "景点5"}
    assert [stay.name for stay in workspace.itinerary.lodging_stays] == ["good_hotel"]
    assert {block.day_id for block in workspace.itinerary.custom_blocks} == {"day_4"}
    assert all(slot.context.get("day_id") not in {"day_1", "day_2", "day_3"} for slot in workspace.selection_slots)


def test_no_conflicts_returns_valid_independent_copy():
    skeleton = _draft(_day(1, _visit("a", 1)))
    result = build_partial_closeout(skeleton, make_catalog(make_visit_packet("a", "景点")), [])
    assert result == skeleton and result is not skeleton
    assert result.days[0] is not skeleton.days[0]
