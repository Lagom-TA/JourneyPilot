"""Integrations routes amap."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from travel_agent.config import get_settings
from travel_agent.integrations.routes.service_days import nominal_service_day_conflict
from travel_agent.runtime.rate_gate import rate_gate_for
from travel_agent.utils.coordinates import gcj02_to_wgs84
from travel_agent.utils.coordinates import wgs84_to_gcj02
from travel_agent.utils.log_redaction import install_query_secret_redaction
from typing import Any
from typing import Dict
from typing import List
from typing import Literal
from typing import Optional
from typing import Tuple
from zoneinfo import ZoneInfo
import hashlib
import httpx
import math


install_query_secret_redaction()


AmapRouteMode = Literal["public_transit", "walk", "drive", "bike"]


_MODE_PATHS: Dict[AmapRouteMode, str] = {
    "public_transit": "/v3/direction/transit/integrated",
    "walk": "/v3/direction/walking",
    "drive": "/v3/direction/driving",
    "bike": "/v4/direction/bicycling",
}


_LINE_KIND_MODES: Tuple[Tuple[str, str], ...] = (
    ("地铁", "metro"),
    ("轻轨", "metro"),
    ("magnet", "train"),
    ("磁悬浮", "train"),
    ("有轨电车", "tram"),
    ("电车", "tram"),
    ("城际", "train"),
    ("动车", "high_speed_rail"),
    ("高铁", "high_speed_rail"),
)


_RATE_GATE_KEY = "mcp:amap-maps"


_UNBOUNDED_KEYS = frozenset({"polyline", "steps", "via_stops", "tmcs"})


def _bounded(value: Any) -> Any:
    """Drop geometry and per-step narration at every depth."""
    if isinstance(value, dict):
        return {
            key: _bounded(item)
            for key, item in value.items()
            if key not in _UNBOUNDED_KEYS
        }
    if isinstance(value, list):
        return [_bounded(item) for item in value]
    return value


def _bounded_payload(payload: Dict[str, Any], *, mode: AmapRouteMode) -> Dict[str, Any]:
    """One plan, no geometry — the exact answer this tool promises to return.

    amap offers five transit plans and the normalizer takes the first; the other
    four are competing options nothing reads. Keeping them would put four unread
    itineraries into the evidence snapshot and the model's context.
    """
    bounded = _bounded(payload)
    envelope = bounded.get("data") if mode == "bike" else bounded.get("route")
    if not isinstance(envelope, dict):
        return bounded
    for key in ("transits", "paths"):
        plans = envelope.get(key)
        if isinstance(plans, list) and len(plans) > 1:
            envelope[key] = plans[:1]
    return bounded


class AmapRouteSearchError(RuntimeError):
    """amap could not return an executable route for this query."""


def _api_key() -> str:
    """The amap web-service key, read from the one place it is configured.

    It lives on the ``amap-maps`` MCP server entry because that is where it was
    first needed; this reader does not add a second config field for the same
    secret. ``_env_mapping`` already lets the process environment win there, so
    a deployment that sets ``AMAP_MAPS_API_KEY`` needs no file change.
    """
    server = get_settings().mcp_servers.get("amap-maps")
    key = (
        str((server.env or {}).get("AMAP_MAPS_API_KEY") or "").strip() if server else ""
    )
    if not key:
        raise AmapRouteSearchError("amap route provider is not configured")
    return key


def _endpoint(
    name: str,
    place_id: str,
    latitude: float,
    longitude: float,
) -> Dict[str, Any]:
    return {
        "name": name,
        "place_id": place_id,
        "latitude": latitude,
        "longitude": longitude,
    }


def _stop_endpoint(raw: Any, *, fallback: Dict[str, Any]) -> Dict[str, Any]:
    """One amap transit stop as an endpoint, with its GCJ-02 point converted."""
    if not isinstance(raw, dict):
        return dict(fallback)
    name = str(raw.get("name") or "").strip()
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location = str(raw.get("location") or "")
    if "," in location:
        try:
            raw_longitude, raw_latitude = (
                float(part) for part in location.split(",", 1)
            )
        except ValueError:
            raw_longitude = raw_latitude = None
        if raw_longitude is not None and raw_latitude is not None:
            longitude, latitude = gcj02_to_wgs84(raw_longitude, raw_latitude)
    if not name:
        return dict(fallback)
    stop_id = str(raw.get("id") or "").strip()
    return {
        "name": name,
        "place_id": f"amap:stop:{stop_id}" if stop_id else fallback["place_id"],
        "latitude": latitude if latitude is not None else fallback["latitude"],
        "longitude": longitude if longitude is not None else fallback["longitude"],
    }


def _seconds_to_minutes(value: Any) -> Optional[int]:

    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return max(0, math.ceil(seconds / 60.0))


def _meters(value: Any) -> Optional[int]:
    try:
        return max(0, int(round(float(value))))
    except (TypeError, ValueError):
        return None


def _yuan(value: Any) -> Optional[float]:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def _line_mode(line_kind: str) -> str:
    for keyword, mode in _LINE_KIND_MODES:
        if keyword in line_kind:
            return mode
    return "bus"


def _segment(
    index: int,
    *,
    mode: str,
    from_endpoint: Dict[str, Any],
    to_endpoint: Dict[str, Any],
    duration_minutes: Optional[int],
    distance_meters: Optional[int],
    line_name: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "segment_id": f"segment_{index}",
        "mode": mode,
        "from_endpoint": from_endpoint,
        "to_endpoint": to_endpoint,
        "departure_at": None,
        "arrival_at": None,
        "duration_minutes": duration_minutes,
        "distance_meters": distance_meters,
        "operator_name": None,
        "service_number": None,
        "line_name": line_name,
        "cost_cny": None,
    }


def _transit_segments(
    transit: Dict[str, Any],
    *,
    origin: Dict[str, Any],
    destination: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Flatten one amap transit plan into ordered walk and line segments.

    amap nests a walk and a ridden line inside a single ``segments`` entry, so
    one entry can become two of ours. Zero-distance walks are dropped: amap emits
    them between a station exit and the next entrance, and a 0 m leg is not a
    journey anybody takes.
    """
    segments: List[Dict[str, Any]] = []
    cursor = dict(origin)
    for entry in transit.get("segments") or ():
        if not isinstance(entry, dict):
            continue
        walking = entry.get("walking")
        lines = (
            ((entry.get("bus") or {}).get("buslines") or [])
            if isinstance(entry.get("bus"), dict)
            else []
        )
        ridden = next((line for line in lines if isinstance(line, dict)), None)
        if isinstance(walking, dict):
            distance = _meters(walking.get("distance"))
            if distance:
                target = (
                    _stop_endpoint(ridden.get("departure_stop"), fallback=destination)
                    if ridden is not None
                    else dict(destination)
                )
                segments.append(
                    _segment(
                        len(segments) + 1,
                        mode="walk",
                        from_endpoint=cursor,
                        to_endpoint=target,
                        duration_minutes=_seconds_to_minutes(walking.get("duration")),
                        distance_meters=distance,
                    )
                )
                cursor = target
        if ridden is None:
            continue
        boarding = _stop_endpoint(ridden.get("departure_stop"), fallback=cursor)
        alighting = _stop_endpoint(ridden.get("arrival_stop"), fallback=destination)
        line_name = str(ridden.get("name") or "").strip() or None
        segments.append(
            _segment(
                len(segments) + 1,
                mode=_line_mode(str(ridden.get("type") or "")),
                from_endpoint=boarding,
                to_endpoint=alighting,
                duration_minutes=_seconds_to_minutes(ridden.get("duration")),
                distance_meters=_meters(ridden.get("distance")),
                line_name=line_name,
            )
        )
        cursor = alighting
    if not segments:
        return []

    segments[0] = {**segments[0], "from_endpoint": dict(origin)}
    segments[-1] = {**segments[-1], "to_endpoint": dict(destination)}
    return segments


def _route_id(material: Any) -> str:
    return f"amap:{hashlib.sha256(repr(material).encode()).hexdigest()[:24]}"


def _normalize_route(
    payload: Dict[str, Any],
    *,
    mode: AmapRouteMode,
    origin: Dict[str, Any],
    destination: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if mode == "public_transit":
        transits = (payload.get("route") or {}).get("transits") or []
        transit = next((item for item in transits if isinstance(item, dict)), None)
        if transit is None:
            return None
        segments = _transit_segments(transit, origin=origin, destination=destination)
        if not segments:
            return None
        ridden = [item for item in segments if item["mode"] != "walk"]
        selected_mode = ridden[0]["mode"] if ridden else "walk"
        duration_minutes = _seconds_to_minutes(transit.get("duration"))
        return {
            "route_id": _route_id(segments),
            "provider": "amap",
            "transport_class": "public_transit" if ridden else "flexible",
            "selected_mode": selected_mode,
            "from_endpoint": segments[0]["from_endpoint"],
            "to_endpoint": segments[-1]["to_endpoint"],
            "departure_at": None,
            "arrival_at": None,
            "duration_minutes": duration_minutes if duration_minutes is not None else 0,
            "distance_meters": _meters(transit.get("distance")),
            "total_cost_cny": _yuan(transit.get("cost")),
            "segments": segments,
            "booking_status": "not_required",
        }

    envelope = payload.get("data") if mode == "bike" else payload.get("route")
    paths = (envelope or {}).get("paths") or []
    path = next((item for item in paths if isinstance(item, dict)), None)
    if path is None:
        return None
    street_mode = {"walk": "walk", "drive": "drive", "bike": "bike"}[mode]
    duration_minutes = _seconds_to_minutes(path.get("duration"))
    segment = _segment(
        1,
        mode=street_mode,
        from_endpoint=dict(origin),
        to_endpoint=dict(destination),
        duration_minutes=duration_minutes,
        distance_meters=_meters(path.get("distance")),
    )
    return {
        "route_id": _route_id(segment),
        "provider": "amap",
        "transport_class": "flexible",
        "selected_mode": street_mode,
        "from_endpoint": dict(origin),
        "to_endpoint": dict(destination),
        "departure_at": None,
        "arrival_at": None,
        "duration_minutes": duration_minutes if duration_minutes is not None else 0,
        "distance_meters": segment["distance_meters"],
        "total_cost_cny": None,
        "segments": [segment],
        "booking_status": "not_required",
    }


async def search_amap_route_raw(
    *,
    from_latitude: float,
    from_longitude: float,
    to_latitude: float,
    to_longitude: float,
    mode: AmapRouteMode,
    departure_time: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Return the complete response for one bounded amap Directions query."""
    settings = get_settings().routing
    server = get_settings().mcp_servers.get("amap-maps")
    min_interval = float(server.min_interval_seconds) if server is not None else 0.0
    key = _api_key()

    origin_longitude, origin_latitude = wgs84_to_gcj02(from_longitude, from_latitude)
    target_longitude, target_latitude = wgs84_to_gcj02(to_longitude, to_latitude)
    params: Dict[str, Any] = {
        "origin": f"{origin_longitude:.6f},{origin_latitude:.6f}",
        "destination": f"{target_longitude:.6f},{target_latitude:.6f}",
        "key": key,
    }
    if mode == "public_transit":
        params["strategy"] = 0
        if departure_time:
            local_departure = datetime.fromisoformat(departure_time).astimezone(
                ZoneInfo("Asia/Shanghai")
            )
            params["date"] = local_departure.strftime("%Y-%m-%d")
            params["time"] = local_departure.strftime("%H:%M")
    owns_client = client is None
    resolved_client = client or httpx.AsyncClient(
        timeout=settings.timeout_seconds,
        headers={"User-Agent": settings.user_agent},
    )
    try:
        await rate_gate_for(_RATE_GATE_KEY).acquire(min_interval)
        response = await resolved_client.get(
            f"{settings.amap_base_url.rstrip('/')}{_MODE_PATHS[mode]}",
            params=params,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AmapRouteSearchError("amap route provider unavailable") from exc
    finally:
        if owns_client:
            await resolved_client.aclose()
    if not isinstance(payload, dict):
        raise AmapRouteSearchError("amap route provider returned an invalid payload")

    if mode == "bike":
        if str(payload.get("errcode") or "0") != "0":
            raise AmapRouteSearchError("amap route provider refused the query")
    elif str(payload.get("status") or "") != "1":
        raise AmapRouteSearchError("amap route provider refused the query")
    if mode == "public_transit" and departure_time:
        route = payload.get("route")
        if isinstance(route, dict) and isinstance(route.get("transits"), list):
            route["transits"] = [
                transit
                for transit in route["transits"]
                if isinstance(transit, dict)
                and not nominal_service_day_conflict(
                    (
                        line.get("name")
                        for segment in transit.get("segments", [])
                        for line in (segment.get("bus") or {}).get("buslines", [])
                        if isinstance(line, dict)
                    ),
                    local_departure.date(),
                )
            ]

    return _bounded_payload(payload, mode=mode)


async def amap_route_search(
    *,
    from_name: str,
    from_place_id: str,
    from_latitude: float,
    from_longitude: float,
    to_name: str,
    to_place_id: str,
    to_latitude: float,
    to_longitude: float,
    departure_time: str,
    mode: AmapRouteMode,
) -> Dict[str, Any]:
    """One exact normalized amap route plus its full provider snapshot."""
    raw = await search_amap_route_raw(
        from_latitude=from_latitude,
        from_longitude=from_longitude,
        to_latitude=to_latitude,
        to_longitude=to_longitude,
        mode=mode,
        departure_time=departure_time,
    )
    route = _normalize_route(
        raw,
        mode=mode,
        origin=_endpoint(from_name, from_place_id, from_latitude, from_longitude),
        destination=_endpoint(to_name, to_place_id, to_latitude, to_longitude),
    )
    if route is None:
        raise AmapRouteSearchError("amap route provider found no executable route")
    observed_at = datetime.now(timezone.utc).isoformat()
    return {
        "success": True,
        "provider": "amap",
        "provider_api_version": "amap-v3",
        "source_attribution_url": "https://lbs.amap.com/api/webservice/guide/api/direction",
        "request": {
            "from_name": from_name,
            "from_place_id": from_place_id,
            "to_name": to_name,
            "to_place_id": to_place_id,
            "departure_time": departure_time,
            "mode": mode,
        },
        "routes": [route],
        "provider_response": raw,
        "observed_at": observed_at,
        "retrieved_at": observed_at,
    }
