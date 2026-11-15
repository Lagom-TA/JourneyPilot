"""Photon 自动补全的离线接口测试。"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from travel_agent.api.routes import places
from travel_agent.integrations.places import photon
from travel_agent.storage.place_search_cache import _search_cache_digest


def feature(name, osm_key, osm_value, osm_type="N", osm_id=1, **updates):
    properties = {
        "name": name,
        "osm_key": osm_key,
        "osm_value": osm_value,
        "osm_type": osm_type,
        "osm_id": osm_id,
        "countrycode": "CN",
        "country": "中国",
    }
    properties.update(updates)
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [116.4, 39.9]},
        "properties": properties,
    }


@pytest.fixture
def offline_cache(monkeypatch):
    cache = type("Cache", (), {})()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    monkeypatch.setattr(photon, "_SEARCH_CACHE", cache)
    monkeypatch.setattr(photon._PHOTON_RATE_GATE, "acquire", AsyncMock())
    return cache


def api_client():
    app = FastAPI()
    app.include_router(places.router)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://offline.test"
    )


async def test_search_maps_identity_filters_roles_and_uses_photon(monkeypatch, offline_cache):
    airport = feature("首都机场", "aeroway", "aerodrome", "W", 222, city="北京", state="北京")
    station = feature("北京南站", "railway", "station", "N", 333, city="北京", state="北京")
    city = feature("北京", "place", "state", "R", 444, city="北京", state="北京")
    scenic = feature("长城", "boundary", "national_park", "W", 555, city="北京", state="北京")
    poi = feature("故宫", "tourism", "museum", "R", 666, city="北京", state="北京")
    invalid = feature("损坏数据", "place", "city", osm_id=0)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"type": "FeatureCollection", "features": [
            airport, station, city, scenic, poi, invalid, None,
        ]})

    original_search = photon.search_photon_raw
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        async def search(query, *, limit):
            return await original_search(query, limit=limit, client=upstream)

        monkeypatch.setattr(places, "search_photon_raw", search)
        async with api_client() as api:
            origin = await api.get("/api/places/search", params={"q": "  北 京  ", "role": "origin"})
            destination = await api.get("/api/places/search", params={"q": "北京", "role": "destination"})
            itinerary = await api.get("/api/places/search", params={"q": "北京", "role": "itinerary_place"})

    assert origin.status_code == destination.status_code == itinerary.status_code == 200
    payload = origin.json()
    assert payload["query"] == "  北 京  "
    assert payload["role"] == "origin"
    assert [item["place"]["kind"] for item in payload["candidates"]] == ["airport", "city"]
    assert payload["candidates"][0] == {
        "place": {
            "place_id": "osm:way:222", "provider": "osm", "kind": "airport",
            "name": "首都机场", "display_name": "首都机场, 北京, 中国", "country_code": "cn",
            "latitude": 39.9, "longitude": 116.4, "admin_path": ["中国", "北京"],
        },
        "confidence": 0.5,
        "requires_confirmation": True,
    }
    assert [item["place"]["place_id"] for item in destination.json()["candidates"]] == ["osm:relation:444", "osm:way:555"]
    assert [item["place"]["kind"] for item in itinerary.json()["candidates"]] == ["scenic_area", "poi"]
    assert all(str(request.url).startswith("https://photon.komoot.io/api/") for request in requests)
    assert dict(requests[0].url.params) == {"q": "北 京", "limit": "15"}
    assert requests[0].headers["user-agent"]
    assert offline_cache.set.await_count == 3
    digest = _search_cache_digest("https://photon.komoot.io/api/", {"q": "北 京", "limit": 15})
    assert offline_cache.get.await_args_list[0].args == (digest,)
    assert len(offline_cache.set.await_args_list[0].args[1].items) == 4


@pytest.mark.parametrize(
    "key,value,feature_type,expected",
    [
        ("place", "town", "", "city"),
        ("place", "municipality", "", "city"),
        ("place", "region", "", "administrative_area"),
        ("boundary", "administrative", "county", "administrative_area"),
        ("place", "island", "", "island"),
        ("aeroway", "airport", "", "airport"),
        ("leisure", "nature_reserve", "", "scenic_area"),
        ("tourism", "hotel", "", "hotel"),
        ("amenity", "restaurant", "", "restaurant"),
        ("historic", "castle", "", "poi"),
    ],
)
def test_place_kinds(key, value, feature_type, expected):
    place = photon.photon_trip_place(feature("示例", key, value, type=feature_type))
    assert place is not None and place["kind"] == expected


def test_invalid_identity_fields_are_skipped():
    def with_geometry(value):
        item = feature("地点", "place", "city")
        item["geometry"] = value
        return item

    invalid = [
        feature("", "place", "city"),
        feature("地点", "place", "city", countrycode="1!"),
        feature("地点", "place", "city", osm_id=True),
        feature("地点", "place", "city", osm_id="-1"),
        feature("地点", "place", "city", osm_type="X"),
        with_geometry({"type": "Point", "coordinates": [181, 39]}),
        with_geometry({"type": "Point", "coordinates": [116, float("nan")]}),
        with_geometry({"type": "LineString", "coordinates": [116, 39]}),
        with_geometry({"type": "Point", "coordinates": [True, 39]}),
    ]
    assert all(photon.photon_trip_place(item) is None for item in invalid)
    assert photon.photon_trip_place(feature("北京", "place", "state", countrycode="US"))["kind"] == "administrative_area"
    assert photon.photon_trip_place(feature("长沙", "place", "village", type="city")) is None
    assert photon.photon_trip_place(feature("北京南站", "railway", "station")) is None


async def test_cache_only_nonempty_results_and_limit_after_role_filter(monkeypatch, offline_cache):
    features = [feature("机场", "aeroway", "airport", osm_id=1)] + [
        feature(f"城市{i}", "place", "city", osm_id=i + 2) for i in range(10)
    ]
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"features": features})

    original_search = photon.search_photon_raw
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        async def search(query, *, limit):
            return await original_search(query, limit=limit, client=upstream)

        monkeypatch.setattr(places, "search_photon_raw", search)
        async with api_client() as api:
            response = await api.get("/api/places/search", params={"q": "城市", "role": "destination"})
        offline_cache.get.return_value = offline_cache.set.await_args.args[1]
        cached = await original_search("城市", limit=15, client=upstream)
        assert len(cached.items) == 11 and len(calls) == 1
        offline_cache.get.return_value = None
        features.clear()
        await original_search("空结果", client=upstream)
        assert offline_cache.set.await_count == 1

    assert len(response.json()["candidates"]) == 5
    assert all(candidate["place"]["kind"] == "city" for candidate in response.json()["candidates"])


@pytest.mark.parametrize("failure", ["429", "500", "timeout", "non_json", "invalid_payload"])
async def test_provider_errors_return_503_without_search_text(monkeypatch, offline_cache, caplog, failure):
    secret = "private-place-query"
    requests = []

    def handler(request):
        requests.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if failure in {"429", "500"}:
            return httpx.Response(int(failure))
        if failure == "non_json":
            return httpx.Response(200, text="not-json")
        return httpx.Response(200, json={"features": {}})

    original_search = photon.search_photon_raw
    caplog.set_level(logging.INFO, logger="httpx")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        async def search(query, *, limit):
            return await original_search(query, limit=limit, client=upstream)

        monkeypatch.setattr(places, "search_photon_raw", search)
        async with api_client() as api:
            response = await api.get("/api/places/search", params={"q": secret, "role": "origin"})
            invalid_query = await api.get("/api/places/search", params={"q": "   ", "role": "origin"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "place_provider_unavailable"
    assert invalid_query.status_code == 400
    assert invalid_query.json()["detail"]["code"] == "place_query_invalid"
    assert len(requests) == 1
    assert secret not in caplog.text
    offline_cache.set.assert_not_awaited()


def test_uvicorn_access_log_does_not_record_query(caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.access")
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d',
        "127.0.0.1", "GET", "/api/places/search?q=private-place-query&role=origin", "1.1", 200,
    )
    assert "/api/places/search" in caplog.text
    assert "private-place-query" not in caplog.text
