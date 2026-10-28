"""高德路径几何进入归一化合同，原始响应保持有界。"""

from copy import deepcopy

import pytest

from travel_agent.integrations.routes import amap
from travel_agent.planning.transport import TransportSegment
from travel_agent.utils.coordinates import gcj02_to_wgs84


_GCJ_POINTS = [
    (116.397428, 39.909230),
    (116.398428, 39.910230),
    (116.399428, 39.911230),
    (116.400428, 39.912230),
]


def _location(point):
    return f"{point[0]},{point[1]}"


def _polyline(*points):
    return ";".join(_location(point) for point in points)


def _wgs_path(points):
    path = []
    for longitude, latitude in points:
        wgs_longitude, wgs_latitude = gcj02_to_wgs84(longitude, latitude)
        path.append({"latitude": wgs_latitude, "longitude": wgs_longitude})
    return path


def _endpoints():
    return (
        {
            "name": "起点",
            "place_id": "origin",
            "latitude": 39.9,
            "longitude": 116.3,
        },
        {
            "name": "终点",
            "place_id": "destination",
            "latitude": 39.92,
            "longitude": 116.41,
        },
    )


def _normalize(payload, mode):
    origin, destination = _endpoints()
    return amap._normalize_route(
        payload,
        mode=mode,
        origin=origin,
        destination=destination,
    )


def _street_payload(mode):
    path = {
        "duration": "60",
        "distance": "100",
        "steps": [
            {"polyline": _polyline(_GCJ_POINTS[0], _GCJ_POINTS[1])},
            {"polyline": _polyline(_GCJ_POINTS[1], _GCJ_POINTS[2])},
        ],
    }
    if mode == "bike":
        return {"errcode": 0, "data": {"paths": [path]}}
    return {"status": "1", "route": {"paths": [path]}}


@pytest.mark.parametrize("mode", ["walk", "drive", "bike"])
def test_street_steps_become_wgs_paths_without_duplicate_join_points(mode):
    route = _normalize(_street_payload(mode), mode)

    segment = route["segments"][0]
    assert segment["path"] == _wgs_path(_GCJ_POINTS[:3])
    assert len(TransportSegment.model_validate(segment).path) == 3


def test_transit_walking_and_busline_keep_their_own_wgs_paths():
    payload = {
        "status": "1",
        "route": {
            "transits": [
                {
                    "duration": "600",
                    "distance": "2000",
                    "segments": [
                        {
                            "walking": {
                                "duration": "60",
                                "distance": "100",
                                "steps": [
                                    {
                                        "polyline": _polyline(
                                            _GCJ_POINTS[0], _GCJ_POINTS[1]
                                        )
                                    },
                                    {
                                        "polyline": _polyline(
                                            _GCJ_POINTS[1], _GCJ_POINTS[2]
                                        )
                                    },
                                ],
                            },
                            "bus": {
                                "buslines": [
                                    {
                                        "name": "1路",
                                        "type": "bus",
                                        "duration": "540",
                                        "distance": "1900",
                                        "departure_stop": {
                                            "name": "上车站",
                                            "location": _location(_GCJ_POINTS[2]),
                                        },
                                        "arrival_stop": {
                                            "name": "下车站",
                                            "location": _location(_GCJ_POINTS[3]),
                                        },
                                        "polyline": _polyline(
                                            _GCJ_POINTS[2], _GCJ_POINTS[3]
                                        ),
                                    }
                                ]
                            },
                        }
                    ],
                }
            ]
        },
    }

    route = _normalize(payload, "public_transit")

    assert [segment["path"] for segment in route["segments"]] == [
        _wgs_path(_GCJ_POINTS[:3]),
        _wgs_path(_GCJ_POINTS[2:]),
    ]


async def test_route_search_fetches_once_and_keeps_geometry_out_of_raw_snapshots(
    monkeypatch,
):
    payload = _street_payload("walk")
    payload["route"]["paths"].append(
        {"duration": "120", "distance": "200", "steps": []}
    )
    calls = []

    async def fake_fetch(**kwargs):
        calls.append(kwargs)
        return deepcopy(payload)

    monkeypatch.setattr(amap, "_fetch_amap_route_payload", fake_fetch)
    query = {
        "from_latitude": 39.9,
        "from_longitude": 116.3,
        "to_latitude": 39.92,
        "to_longitude": 116.41,
        "mode": "walk",
    }

    raw = await amap.search_amap_route_raw(**query)

    assert len(calls) == 1
    assert raw == {
        "status": "1",
        "route": {"paths": [{"duration": "60", "distance": "100"}]},
    }

    calls.clear()
    result = await amap.amap_route_search(
        from_name="起点",
        from_place_id="origin",
        to_name="终点",
        to_place_id="destination",
        departure_time="2026-10-27T10:00:00+08:00",
        **query,
    )

    assert len(calls) == 1
    assert result["routes"][0]["segments"][0]["path"] == _wgs_path(
        _GCJ_POINTS[:3]
    )
    assert result["provider_response"] == raw
