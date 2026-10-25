"""Planning research accommodation parsing."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional

from travel_agent.integrations.place_identity import stable_place_id_amap_poi
from travel_agent.integrations.places.normalization import is_concrete_lodging_place
from travel_agent.integrations.places.taxonomy import (
    provider_place_type_matches_candidate_kind,
)
from travel_agent.utils.coordinates import amap_location_to_wgs84

_AMAP_LODGING_TYPECODE_PREFIXES = ("1001", "1002")


_AMAP_LODGING_TYPECODE_EXACT = {"100000"}


_AMAP_HOTELS_PER_CITY = 5


def _extract_tool_text(envelope: Mapping[str, Any]) -> str:
    """Collect any text payload from an MCP tool envelope, defensively."""
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

    walk(envelope.get("sanitized_result"))
    if not parts:
        summary = envelope.get("result_summary")
        if isinstance(summary, str):
            parts.append(summary)
    return "\n".join(parts)


def _is_amap_lodging_typecode(typecode: str) -> bool:
    for code in str(typecode or "").split("|"):
        code = code.strip()
        if code in _AMAP_LODGING_TYPECODE_EXACT or code.startswith(
            _AMAP_LODGING_TYPECODE_PREFIXES
        ):
            return True
    return False


def _amap_lodging_type_label(typecode: str) -> str:
    """Project an amap 住宿 typecode into a label carrying a lodging marker."""
    first = ""
    for code in str(typecode or "").split("|"):
        code = code.strip()
        if code:
            first = code
            break
    if first.startswith("1002"):
        label = "旅馆招待所"
    elif first.startswith("1001"):
        label = "宾馆酒店"
    else:
        label = "住宿服务·酒店"
    return f"{label}（amap typecode {typecode}）"


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


def _lodging_place_record(
    poi_id: str,
    name: str,
    address: str,
    typecode: str,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Project one amap POI into a global_place_search-shaped lodging record."""
    poi_id, name, address, typecode = (
        poi_id.strip(),
        name.strip(),
        address.strip(),
        typecode.strip(),
    )
    if not poi_id or not name or not address or not typecode:
        return None
    if not _is_amap_lodging_typecode(typecode):
        return None
    place_id = stable_place_id_amap_poi(poi_id)
    if place_id is None:
        return None
    record: Dict[str, Any] = {
        "place_id": place_id,
        "provider": "amap",
        "provider_place_type": _amap_lodging_type_label(typecode),
        "provider_country_code": "cn",
        "name": name,
        "address": address,
    }

    if isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)):
        record["latitude"] = float(latitude)
        record["longitude"] = float(longitude)
    return record


def _hotels_from_pois(pois: Any) -> List[Dict[str, Any]]:
    """Project the mcp_manager-normalized amap ``pois`` list into place records."""
    hotels: List[Dict[str, Any]] = []
    for poi in pois or []:
        if not isinstance(poi, dict):
            continue
        latitude = poi.get("latitude")
        longitude = poi.get("longitude")
        if latitude is None or longitude is None:
            latitude, longitude = amap_location_to_wgs84(poi.get("location"))
        record = _lodging_place_record(
            str(poi.get("id") or ""),
            str(poi.get("name") or ""),
            str(poi.get("address") or ""),
            str(poi.get("typecode") or ""),
            latitude if isinstance(latitude, (int, float)) else None,
            longitude if isinstance(longitude, (int, float)) else None,
        )
        if record is not None:
            hotels.append(record)
        if len(hotels) >= _AMAP_HOTELS_PER_CITY:
            break
    return hotels


def _parse_amap_hotels(text: str) -> List[Dict[str, Any]]:
    """Regex fallback: recover lodging POIs from raw amap text (truncation-safe)."""
    hotels: List[Dict[str, Any]] = []
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
        record = _lodging_place_record(
            match.group("id"),
            match.group("name"),
            match.group("address"),
            match.group("typecode"),
            latitude,
            longitude,
        )
        if record is not None:
            hotels.append(record)
        if len(hotels) >= _AMAP_HOTELS_PER_CITY:
            break
    return hotels


def _build_place_search_envelope(
    *,
    results: List[Dict[str, Any]],
    provider: str,
    server_name: str,
    audit_id: str,
    retrieved_at: str,
) -> Dict[str, Any]:
    """Wrap deterministically bound lodging places as a Provider place envelope."""
    return {
        "tool_name": "global_place_search",
        "server_name": server_name,
        "status": "success",
        "audit_id": audit_id,
        "retrieved_at": retrieved_at,
        "metadata": {"evidence_allowed": True},
        "sanitized_result": {
            "success": True,
            "provider": provider,
            "results": results,
        },
    }


_NOMINATIM_HOTELS_PER_CITY = 5


def _nominatim_hotels_from_results(results: List[Any]) -> List[Dict[str, Any]]:
    """Keep the concrete lodging-typed Provider records, in Provider order."""
    hotels: List[Dict[str, Any]] = []
    bound_place_ids: List[str] = []
    for item in results:
        if not isinstance(item, Mapping):
            continue
        record = dict(item)
        place_id = str(record.get("place_id") or "").strip()
        if not place_id or place_id in bound_place_ids:
            continue

        if not all(
            isinstance(record.get(field), str) and record[field].strip()
            for field in (
                "provider",
                "provider_place_type",
                "provider_country_code",
                "name",
                "address",
            )
        ):
            continue
        if not provider_place_type_matches_candidate_kind(
            record["provider_place_type"],
            "lodging",
        ):
            continue
        if not is_concrete_lodging_place(record):
            continue
        hotels.append(record)
        bound_place_ids.append(place_id)
        if len(hotels) >= _NOMINATIM_HOTELS_PER_CITY:
            break
    return hotels
