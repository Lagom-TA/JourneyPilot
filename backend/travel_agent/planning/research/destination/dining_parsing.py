"""Planning research destination dining parsing."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from travel_agent.integrations.place_identity import stable_place_id_amap_poi
from travel_agent.utils.coordinates import amap_location_to_wgs84

_AMAP_DINING_TYPECODE_PREFIXES = ("050",)


_AMAP_DINING_PER_CITY = 5


_AMAP_POI_RE = re.compile(
    r'"id"\s*:\s*"(?P<id>[^"]+)"'
    r'[^{}]*?"name"\s*:\s*"(?P<name>[^"]+)"'
    r'[^{}]*?"address"\s*:\s*"(?P<address>[^"]*)"'
    r'[^{}]*?"typecode"\s*:\s*"(?P<typecode>[^"]+)"',
    re.DOTALL,
)


_AMAP_LOCATION_RE = re.compile(
    r'"location"\s*:\s*"(?P<lng>-?\d+(?:\.\d+)?)\s*,\s*(?P<lat>-?\d+(?:\.\d+)?)"'
)


def _extract_amap_tool_text(envelope: Dict[str, Any] | Any) -> str:
    parts: List[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            text = node.get("text")
            if node.get("type") == "text" and isinstance(text, str):
                parts.append(text)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    if isinstance(envelope, dict):
        walk(envelope.get("sanitized_result"))
        if not parts:
            summary = envelope.get("result_summary")
            if isinstance(summary, str):
                parts.append(summary)
    return "\n".join(parts)


def _is_amap_dining_typecode(typecode: str) -> bool:
    for code in str(typecode or "").split("|"):
        code = code.strip()
        if any(code.startswith(prefix) for prefix in _AMAP_DINING_TYPECODE_PREFIXES):
            return True
    return False


def _amap_dining_type_label(typecode: str) -> str:
    """provider_place_type must carry dining admission markers (餐饮服务/餐厅)."""
    first = ""
    for code in str(typecode or "").split("|"):
        code = code.strip()
        if code:
            first = code
            break
    if first.startswith("0505"):
        kind = "咖啡厅"
    elif first.startswith("0506"):
        kind = "茶艺馆"
    elif first.startswith("0503"):
        kind = "快餐厅"
    elif first.startswith("0502"):
        kind = "外国餐厅"
    elif first.startswith("0501"):
        kind = "中餐厅"
    else:
        kind = "餐饮服务"
    return f"餐饮服务·{kind}（amap typecode {typecode}）"


def _dining_place_record(
    poi_id: str,
    name: str,
    address: str,
    typecode: str,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    poi_id, name, address, typecode = (
        poi_id.strip(),
        name.strip(),
        address.strip(),
        typecode.strip(),
    )
    if not poi_id or not name or not address or not typecode:
        return None
    if not _is_amap_dining_typecode(typecode):
        return None
    place_id = stable_place_id_amap_poi(poi_id)
    if place_id is None:
        return None
    record: Dict[str, Any] = {
        "place_id": place_id,
        "provider": "amap",
        "provider_place_type": _amap_dining_type_label(typecode),
        "provider_country_code": "cn",
        "name": name,
        "address": address,
    }
    if isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)):
        record["latitude"] = float(latitude)
        record["longitude"] = float(longitude)
    return record


def _restaurants_from_pois(pois: Any) -> List[Dict[str, Any]]:
    restaurants: List[Dict[str, Any]] = []
    for poi in pois or []:
        if not isinstance(poi, dict):
            continue
        latitude = poi.get("latitude")
        longitude = poi.get("longitude")
        if latitude is None or longitude is None:
            latitude, longitude = amap_location_to_wgs84(poi.get("location"))
        record = _dining_place_record(
            str(poi.get("id") or ""),
            str(poi.get("name") or ""),
            str(poi.get("address") or ""),
            str(poi.get("typecode") or ""),
            latitude if isinstance(latitude, (int, float)) else None,
            longitude if isinstance(longitude, (int, float)) else None,
        )
        if record is not None:
            restaurants.append(record)
        if len(restaurants) >= _AMAP_DINING_PER_CITY:
            break
    return restaurants


def _parse_amap_restaurants(text: str) -> List[Dict[str, Any]]:
    restaurants: List[Dict[str, Any]] = []
    source = text or ""
    for match in _AMAP_POI_RE.finditer(source):
        object_start = source.rfind("{", 0, match.start())
        object_end = source.find("}", match.end())
        object_span = source[
            object_start if object_start != -1 else match.start() : object_end
            if object_end != -1
            else match.end() + 200
        ]
        location_match = _AMAP_LOCATION_RE.search(object_span)
        latitude, longitude = (
            amap_location_to_wgs84(
                f"{location_match.group('lng')},{location_match.group('lat')}"
            )
            if location_match is not None
            else (None, None)
        )
        record = _dining_place_record(
            match.group("id"),
            match.group("name"),
            match.group("address"),
            match.group("typecode"),
            latitude,
            longitude,
        )
        if record is not None:
            restaurants.append(record)
        if len(restaurants) >= _AMAP_DINING_PER_CITY:
            break
    return restaurants
