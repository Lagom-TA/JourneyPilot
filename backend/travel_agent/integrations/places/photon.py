"""Photon 自动补全与 OSM 地点身份转换。"""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Mapping

import httpx

from travel_agent.config.loader import get_settings
from travel_agent.integrations.place_identity import stable_place_id_osm
from travel_agent.integrations.places.contracts import (
    NominatimPlaceSearchError,
    NominatimSearchObservation,
)
from travel_agent.runtime.rate_gate import rate_gate_for
from travel_agent.storage.place_search_cache import _SEARCH_CACHE, _search_cache_digest


_PHOTON_URL = "https://photon.komoot.io/api/"
_PHOTON_RATE_GATE = rate_gate_for("photon")
_OSM_TYPES = {"N": "node", "W": "way", "R": "relation"}
_COUNTRY_CODE = re.compile(r"[a-z]{2}\Z")
_OSM_ID = re.compile(r"[1-9][0-9]*\Z")
_MUNICIPALITIES = {
    "北京", "北京市", "beijing",
    "上海", "上海市", "shanghai",
    "天津", "天津市", "tianjin",
    "重庆", "重庆市", "重慶", "重慶市", "chongqing",
}


class _PlaceSearchLogFilter(logging.Filter):
    """避免 HTTP 客户端和服务访问日志记录地点搜索内容。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if not isinstance(record.args, tuple):
            return True
        args = list(record.args)
        for index, value in enumerate(args):
            if isinstance(value, httpx.URL):
                if (value.host == "photon.komoot.io" and value.path.rstrip("/") == "/api") or value.path == "/api/places/search":
                    args[index] = value.copy_with(query=None)
            elif isinstance(value, str):
                if record.name == "httpx" and value.startswith(("http://", "https://")):
                    url = httpx.URL(value)
                    if (url.host == "photon.komoot.io" and url.path.rstrip("/") == "/api") or url.path == "/api/places/search":
                        args[index] = str(url.copy_with(query=None))
                elif record.name == "uvicorn.access":
                    path, separator, _ = value.partition("?")
                    if separator and path == "/api/places/search":
                        args[index] = path
        record.args = tuple(args)
        return True


for _logger_name in ("httpx", "uvicorn.access"):
    logging.getLogger(_logger_name).addFilter(_PlaceSearchLogFilter())


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _kind(properties: Mapping[str, Any], *, name: str, country_code: str) -> str | None:
    key = _text(properties.get("osm_key")).casefold()
    value = _text(properties.get("osm_value")).casefold()
    feature_type = _text(properties.get("type")).casefold()
    if key == "aeroway":
        return "airport" if value in {"aerodrome", "airport"} else None
    if key == "railway":
        # Photon 不保证返回区分地铁与火车站的标签，无法确认时不当作出发地。
        return None
    if key == "place" and value == "state" and country_code == "cn" and name.casefold() in _MUNICIPALITIES:
        return "city"
    # Photon 的 type 可能是所属行政层级，只有行政边界可用它识别地区。
    items = (value, feature_type) if key == "boundary" else (value,)
    for item in items:
        if item == "country":
            return "country"
        if item in {"city", "town", "municipality"}:
            return "city"
        if item in {"state", "province", "region", "county"}:
            return "administrative_area"
        if item in {"island", "islet"}:
            return "island"
        if item in {"national_park", "nature_reserve", "protected_area"}:
            return "scenic_area"
        if item in {"hotel", "guest_house", "hostel"}:
            return "hotel"
        if item in {"restaurant", "cafe", "fast_food"}:
            return "restaurant"
    if key in {"tourism", "historic", "leisure", "natural"}:
        return "poi"
    return None


def _unique_texts(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _text(value)
        if text and text.casefold() not in seen:
            result.append(text)
            seen.add(text.casefold())
    return result


def photon_trip_place(feature: Mapping[str, Any]) -> dict[str, Any] | None:
    """只转换具备稳定 OSM 身份、名称、国家码与有效坐标的地点。"""
    properties = feature.get("properties")
    geometry = feature.get("geometry")
    if feature.get("type") != "Feature" or not isinstance(properties, dict) or not isinstance(geometry, dict):
        return None
    if geometry.get("type") != "Point":
        return None
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
        return None
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in coordinates[:2]):
        return None
    try:
        longitude, latitude = (float(value) for value in coordinates[:2])
    except OverflowError:
        return None
    if not math.isfinite(latitude) or not math.isfinite(longitude) or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None

    osm_type = _OSM_TYPES.get(_text(properties.get("osm_type")).upper())
    osm_id = properties.get("osm_id")
    if isinstance(osm_id, bool) or not isinstance(osm_id, (str, int)) or not _OSM_ID.fullmatch(str(osm_id)):
        return None
    place_id = stable_place_id_osm(osm_type or "", str(osm_id))
    name = _text(properties.get("name"))
    country_code = _text(properties.get("countrycode")).lower()
    if place_id is None or not name or not _COUNTRY_CODE.fullmatch(country_code):
        return None
    kind = _kind(properties, name=name, country_code=country_code)
    if kind is None:
        return None

    display_parts = _unique_texts([
        name, properties.get("city"), properties.get("county"),
        properties.get("state"), properties.get("country"),
    ])
    admin_path = _unique_texts([
        properties.get("country"), properties.get("state"),
        properties.get("city"), properties.get("county"),
    ])
    return {
        "place_id": place_id,
        "provider": "osm",
        "kind": kind,
        "name": name,
        "display_name": ", ".join(display_parts),
        "country_code": country_code,
        "latitude": latitude,
        "longitude": longitude,
        "admin_path": admin_path,
    }


async def search_photon_raw(
    query: str,
    *,
    limit: int = 15,
    client: httpx.AsyncClient | None = None,
) -> NominatimSearchObservation:
    """读取并缓存非空的 Photon 搜索响应。"""
    normalized_query = " ".join((query or "").split())
    if not normalized_query:
        raise ValueError("query is required")
    if not 1 <= limit <= 15:
        raise ValueError("limit must be between 1 and 15")
    params = {"q": normalized_query, "limit": limit}
    digest = _search_cache_digest(_PHOTON_URL, params)
    cached = await _SEARCH_CACHE.get(digest)
    if cached is not None:
        return cached

    settings = get_settings().geocoding
    owns_client = client is None
    resolved_client = client or httpx.AsyncClient()
    try:
        await _PHOTON_RATE_GATE.acquire(0.35)
        response = await resolved_client.get(
            _PHOTON_URL,
            params=params,
            headers={"User-Agent": settings.user_agent},
            timeout=min(settings.search_timeout_seconds, 2.5),
        )
        response.raise_for_status()
        try:
            raw = response.json()
        except ValueError as exc:
            raise NominatimPlaceSearchError(
                "photon returned a non-JSON body", code="provider_unparseable"
            ) from exc
    except httpx.HTTPError as exc:
        raise NominatimPlaceSearchError(
            "photon unavailable", code="provider_unavailable"
        ) from exc
    finally:
        if owns_client:
            await resolved_client.aclose()
    if not isinstance(raw, dict) or not isinstance(raw.get("features"), list):
        raise NominatimPlaceSearchError(
            "photon returned an invalid payload", code="provider_invalid_payload"
        )
    items = [
        item for item in raw["features"]
        if isinstance(item, dict) and photon_trip_place(item) is not None
    ]
    observation = NominatimSearchObservation(
        items=items,
        observed_at=datetime.now(timezone.utc),
        origin="live",
    )
    if items:
        await _SEARCH_CACHE.set(digest, observation)
    return observation
