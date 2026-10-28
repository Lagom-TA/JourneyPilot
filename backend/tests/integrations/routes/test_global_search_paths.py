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
