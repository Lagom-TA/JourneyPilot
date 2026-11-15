"""Duffel 共享航班的承运人与号码必须成对使用。"""

from datetime import date

import httpx
import pytest

from travel_agent.integrations.flights.duffel import _segment, search_duffel_flights
from travel_agent.tools.governance import build_tool_execution_envelope


def _raw_segment():
    return {
        "id": "seg_1",
        "origin": {"iata_code": "PVG", "name": "浦东"},
        "destination": {"iata_code": "NRT", "name": "成田"},
        "departing_at": "2026-11-20T09:00:00+08:00",
        "arriving_at": "2026-11-20T13:00:00+09:00",
        "duration": "PT3H",
        "operating_carrier": {"iata_code": "NH", "name": "全日空"},
        "operating_carrier_flight_number": "920",
        "marketing_carrier": {"iata_code": "CA", "name": "国航"},
        "marketing_carrier_flight_number": "6789",
    }


@pytest.mark.parametrize(
    ("changes", "number", "operator"),
    [
        ({}, "NH920", "全日空"),
        ({"operating_carrier_flight_number": None}, "CA6789", "国航"),
        ({"operating_carrier": {"name": "全日空"}}, "CA6789", "国航"),
        ({"marketing_carrier": None}, "NH920", "全日空"),
        ({"operating_carrier": None}, "CA6789", "国航"),
        ({"operating_carrier_flight_number": None, "marketing_carrier": None}, None, "全日空"),
        ({"operating_carrier": {"iata_code": "NH", "name": "全日空"},
          "operating_carrier_flight_number": None,
          "marketing_carrier": {"name": "国航"}}, None, "全日空"),
        ({"operating_carrier_flight_number": "NH920", "marketing_carrier": None}, None, "全日空"),
        ({"operating_carrier": "invalid", "marketing_carrier": None}, None, None),
        ({"operating_carrier": {"iata_code": " nh ", "name": "全日空"},
          "operating_carrier_flight_number": " 920a "}, "NH920A", "全日空"),
    ],
)
def test_flight_number_never_combines_different_carriers(changes, number, operator):
    raw = _raw_segment()
    raw.update(changes)

    segment = _segment(raw, 1)

    assert segment["service_number"] == number
    assert segment["operator_name"] == operator
    assert segment["line_name"] == operator


async def test_duffel_search_keeps_each_real_number_through_gateway_sanitization():
    first = _raw_segment()
    second = _raw_segment()
    second.pop("id")
    second.update(
        origin=first["destination"],
        destination={"iata_code": "HND", "name": "羽田"},
        departing_at="2026-11-20T15:00:00+09:00",
        arriving_at="2026-11-20T16:00:00+09:00", duration="PT1H",
        operating_carrier_flight_number=None, marketing_carrier_flight_number="123",
    )
    response = {"data": {"id": "req_1", "live_mode": True, "offers": [{
        "id": "offer_1", "slices": [{"duration": "PT7H", "segments": [first, second]}],
    }]}}
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=response))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await search_duffel_flights(
            {"origin": "PVG", "destination": "HND", "departure_date": "2026-11-20"},
            token="test-token", client=client, today=date(2026, 11, 1),
        )
    envelope = build_tool_execution_envelope(
        tool_name="search_flights", server_name="duffel-flights", source="mcp",
        arguments={}, result=result,
    )
    segments = envelope["sanitized_result"]["routes"][0]["segments"]
    assert [segment["service_number"] for segment in segments] == ["NH920", "CA123"]
    assert [segment["segment_id"] for segment in segments] == ["seg_1", "segment_2"]
    assert [segment["operator_name"] for segment in segments] == ["全日空", "国航"]
