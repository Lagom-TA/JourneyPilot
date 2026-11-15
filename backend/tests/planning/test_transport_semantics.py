"""换乘只统计已证实的乘坐服务变化。"""

from datetime import date

import pytest
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from travel_agent.planning.research.reference_service_contracts import ProviderReferenceService
from travel_agent.planning.state import TravelAgentState, _merge_reference_services
from travel_agent.planning.transport import TransportEndpoint, TransportSegment
from travel_agent.planning.transport_semantics import count_service_transfers


def _stop(name):
    return TransportEndpoint(name=name)


def _segment(index, mode, *, from_name, to_name, line_name=None, service_number=None):
    return TransportSegment(
        segment_id=f"segment_{index}",
        mode=mode,
        from_endpoint=_stop(from_name),
        to_endpoint=_stop(to_name),
        line_name=line_name,
        service_number=service_number,
    )


def test_walking_access_around_one_metro_line_is_not_a_transfer():
    segments = [
        _segment(1, "walk", from_name="饭店", to_name="地铁站"),
        _segment(2, "metro", from_name="地铁站", to_name="景区站", line_name="1号线"),
        _segment(3, "walk", from_name="景区站", to_name="景区"),
    ]

    assert count_service_transfers(segments) == 0


def test_the_same_metro_line_split_into_two_segments_is_not_a_transfer():
    segments = [
        _segment(1, "metro", from_name="甲站", to_name="乙站", line_name="1号线"),
        _segment(2, "metro", from_name="乙站", to_name="丙站", line_name="1号线"),
    ]

    assert count_service_transfers(segments) == 0


def test_two_different_metro_lines_count_as_one_transfer():
    segments = [
        _segment(1, "metro", from_name="甲站", to_name="乙站", line_name="1号线"),
        _segment(2, "metro", from_name="乙站", to_name="丙站", line_name="2号线"),
    ]

    assert count_service_transfers(segments) == 1


def _reference_service(**updates):
    data = {
        "leg_role": "inter_destination",
        "from_name": "海口东",
        "to_name": "三亚",
        "service_number": "D1",
        "departure_time": "09:00",
        "arrival_time": "10:00",
        "requested_date": "2026-11-13",
        "reference_date": "2026-11-10",
        "unconfirmed_claims": ["train_no", "price", "inventory"],
    }
    data.update(updates)
    return ProviderReferenceService.model_validate(data)


def test_reference_service_accepts_inter_destination_and_keeps_reference_semantics():
    service = _reference_service()
    assert service.leg_role == "inter_destination"
    assert service.unconfirmed_claims == ["train_no", "price", "inventory"]
    assert service.requested_date == date(2026, 11, 13)
    restored = TravelAgentState.model_validate(
        {"provider_reference_services": [service.model_dump()]}
    )
    assert restored.provider_reference_services == [service]
    with pytest.raises(ValidationError, match="only a reference for another date"):
        _reference_service(reference_date="2026-11-13")


def test_reference_service_reducer_keeps_distinct_routes_and_updates_only_the_same_leg():
    first = _reference_service()
    next_leg = _reference_service(from_name="三亚", to_name="陵水", service_number="D2")
    same_origin = _reference_service(to_name="博鳌", service_number="D3")
    same_destination = _reference_service(from_name="文昌", service_number="D7")
    reverse = _reference_service(from_name="三亚", to_name="海口东", service_number="D8")
    next_day = _reference_service(requested_date="2026-11-14", service_number="D4")
    outbound = _reference_service(leg_role="outbound", service_number="D5")
    refreshed = _reference_service(service_number="D6", reference_date="2026-11-11")

    merged = _merge_reference_services(
        [first], [next_leg, same_origin, same_destination, reverse, next_day, outbound]
    )
    assert merged == [
        first, next_leg, same_origin, same_destination, reverse, next_day, outbound
    ]
    assert _merge_reference_services(merged, [refreshed]) == [
        refreshed, next_leg, same_origin, same_destination, reverse, next_day, outbound
    ]
    assert _merge_reference_services(merged, []) == []


def test_reference_services_survive_actual_graph_state_reduction():
    first = _reference_service()
    second = _reference_service(from_name="三亚", to_name="陵水", service_number="D2")
    graph = StateGraph(TravelAgentState)
    graph.add_node("first_leg", lambda _state: {"provider_reference_services": [first]})
    graph.add_node("second_leg", lambda _state: {"provider_reference_services": [second]})
    graph.add_edge(START, "first_leg")
    graph.add_edge("first_leg", "second_leg")
    graph.add_edge("second_leg", END)

    result = graph.compile().invoke(TravelAgentState())
    assert result["provider_reference_services"] == [first, second]
