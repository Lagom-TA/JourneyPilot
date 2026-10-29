"""MOTIS 详细路径按声明精度解码为 WGS-84 点。"""

from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from travel_agent.integrations.routes import global_search
from travel_agent.planning.transport import RoutePathPoint, TransportSegment


def _encode_value(value, output):
    value <<= 1
    if value < 0:
        value = ~value
    while value >= 0x20:
        output.append(chr((0x20 | (value & 0x1F)) + 63))
        value >>= 5
    output.append(chr(value + 63))


def _encode_polyline(points, precision=6):
    factor = 10**precision
    output = []
    previous_latitude = 0
    previous_longitude = 0
    for latitude, longitude in points:
        latitude_value = round(latitude * factor)
        longitude_value = round(longitude * factor)
        _encode_value(latitude_value - previous_latitude, output)
        _encode_value(longitude_value - previous_longitude, output)
        previous_latitude = latitude_value
        previous_longitude = longitude_value
    return {
        "points": "".join(output),
        "precision": precision,
        "length": len(points),
    }


def _normalize(geometry):
    return global_search._normalize_route(
        {
            "id": "itinerary_test",
            "duration": 120,
            "legs": [
                {
                    "mode": "WALK",
                    "from": {},
                    "to": {},
                    "duration": 120,
                    "distance": 100.0,
                    "legGeometry": geometry,
                }
            ],
        },
        mode="walk",
        from_name="Origin",
        from_place_id="origin",
        from_latitude=48.8566,
        from_longitude=2.3522,
        to_name="Destination",
        to_place_id="destination",
        to_latitude=48.857,
        to_longitude=2.36,
        request_departure_time="2026-10-27T10:00:00+02:00",
    )


def test_motis_leg_geometry_becomes_a_path():
    points = [(48.8566, 2.3522), (48.857, 2.36)]

    route = _normalize(_encode_polyline(points))

    segment = route["segments"][0]
    assert segment["path"] == [
        {"latitude": latitude, "longitude": longitude}
        for latitude, longitude in points
    ]
    assert len(TransportSegment.model_validate(segment).path) == 2


@pytest.mark.parametrize(
    "geometry",
    [
        None,
        {"points": "", "precision": 6, "length": 0},
        {"points": "invalid", "precision": 6, "length": 2},
    ],
)
def test_motis_without_usable_geometry_has_an_empty_path(geometry):
    route = _normalize(geometry)

    assert route["segments"][0]["path"] == []


async def test_motis_requests_detailed_leg_geometry(monkeypatch):
    settings = SimpleNamespace(
        routing=SimpleNamespace(
            transitous_base_url="https://transitous.test",
            timeout_seconds=20.0,
            user_agent="JourneyPilot tests",
            min_interval_seconds=0.0,
        )
    )
    monkeypatch.setattr(global_search, "get_settings", lambda: settings)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"direct": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await global_search.search_global_route_raw(
            from_latitude=48.8566,
            from_longitude=2.3522,
            to_latitude=48.857,
            to_longitude=2.36,
            departure_time="2026-10-27T10:00:00+02:00",
            mode="walk",
            client=client,
        )

    assert len(requests) == 1
    assert requests[0].url.params["detailedLegs"] == "true"


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(90.1, 0.0), (-90.1, 0.0), (0.0, 180.1), (0.0, -180.1)],
)
def test_route_path_point_rejects_out_of_range_coordinates(latitude, longitude):
    with pytest.raises(ValidationError):
        RoutePathPoint(latitude=latitude, longitude=longitude)

def test_transit_walk_access_keeps_provider_boarding_and_alighting_stops():
    itinerary = {
        "id": "itinerary_transit",
        "duration": 1200,
        "legs": [
            {
                "mode": "WALK",
                "from": {},
                "to": {},
                "duration": 120,
                "distance": 100.0,
                "legGeometry": None,
            },
            {
                "mode": "SUBWAY",
                "from": {"name": "Origin station", "stopId": "origin_stop", "lat": 48.8566, "lon": 2.3522},
                "to": {"name": "Destination station", "stopId": "destination_stop", "lat": 48.857, "lon": 2.36},
                "duration": 960,
                "distance": 3500.0,
                "legGeometry": None,
                "routeLongName": "M1",
                "tripShortName": "M1",
            },
            {
                "mode": "WALK",
                "from": {},
                "to": {},
                "duration": 120,
                "distance": 100.0,
                "legGeometry": None,
            },
        ],
    }

    route = global_search._normalize_route(
        itinerary,
        mode="public_transit",
        from_name="Origin",
        from_place_id="origin",
        from_latitude=48.8566,
        from_longitude=2.3522,
        to_name="Destination",
        to_place_id="destination",
        to_latitude=48.857,
        to_longitude=2.36,
        request_departure_time="2026-10-27T10:00:00+02:00",
    )

    assert route["from_endpoint"]["place_id"] == "origin"
    assert route["to_endpoint"]["place_id"] == "destination"
    assert route["boarding_stop"]["name"] == "Origin station"
    assert route["boarding_stop"]["place_id"] == "transitous-stop:origin_stop"
    assert route["alighting_stop"]["name"] == "Destination station"
    assert route["alighting_stop"]["place_id"] == "transitous-stop:destination_stop"


def test_transit_boundary_stops_do_not_borrow_intermediate_stations():
    transfer = {
        "name": "Transfer station",
        "stopId": "transfer_stop",
        "lat": 48.857,
        "lon": 2.355,
    }
    itinerary = {
        "id": "itinerary_transfer",
        "duration": 1200,
        "legs": [
            {
                "mode": "SUBWAY",
                "from": {},
                "to": transfer,
                "duration": 600,
                "distance": 1800.0,
                "legGeometry": None,
                "routeLongName": "M1",
                "tripShortName": "M1",
            },
            {
                "mode": "SUBWAY",
                "from": transfer,
                "to": {},
                "duration": 600,
                "distance": 2200.0,
                "legGeometry": None,
                "routeLongName": "M2",
                "tripShortName": "M2",
            },
        ],
    }

    route = global_search._normalize_route(
        itinerary,
        mode="public_transit",
        from_name="Origin",
        from_place_id="origin",
        from_latitude=48.8566,
        from_longitude=2.3522,
        to_name="Destination",
        to_place_id="destination",
        to_latitude=48.857,
        to_longitude=2.36,
        request_departure_time="2026-10-27T10:00:00+02:00",
    )

    assert route["boarding_stop"] is None
    assert route["alighting_stop"] is None
    assert route["from_endpoint"]["place_id"] == "origin"
    assert route["to_endpoint"]["place_id"] == "destination"


@pytest.mark.parametrize("line_names", [("M1", "M1"), ("M1", "M2")])
def test_transit_short_route_names_stay_distinct_from_trip_numbers(line_names):
    stops = [
        {"name": name, "stopId": str(index), "lat": 48.85, "lon": 2.35}
        for index, name in enumerate(("Origin station", "Transfer station", "Destination station"))
    ]
    itinerary = {
        "duration": 1200,
        "legs": [
            {
                "mode": "SUBWAY",
                "from": stops[index],
                "to": stops[index + 1],
                "duration": 600,
                "tripShortName": str(471 + index),
                "routeShortName": line_name,
            }
            for index, line_name in enumerate(line_names)
        ],
    }

    route = global_search._normalize_route(
        itinerary,
        mode="public_transit",
        from_name="Origin",
        from_place_id="origin",
        from_latitude=48.85,
        from_longitude=2.35,
        to_name="Destination",
        to_place_id="destination",
        to_latitude=48.85,
        to_longitude=2.35,
        request_departure_time="2026-10-27T10:00:00+02:00",
    )

    segments = [TransportSegment.model_validate(segment) for segment in route["segments"]]
    assert [segment.line_name for segment in segments] == list(line_names)
    assert [segment.service_number for segment in segments] == ["471", "472"]
    assert route["boarding_stop"]["name"] == "Origin station"
    assert route["alighting_stop"]["name"] == "Destination station"
