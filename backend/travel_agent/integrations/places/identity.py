"""将地点提供方记录转换为旅行基础信息中的地点身份。"""

from __future__ import annotations

from typing import Any, Mapping

from travel_agent.integrations.place_identity import stable_place_id_osm


def _kind(item: Mapping[str, Any]) -> str | None:
    value = str(item.get("addresstype") or item.get("type") or "").lower()
    facility = str(item.get("type") or "").lower()
    category = str(item.get("category") or item.get("class") or "").lower()
    address = item.get("address") if isinstance(item.get("address"), dict) else {}
    subdivision_code = str(address.get("ISO3166-2-lvl4") or address.get("ISO3166-2-lvl3") or "").upper()
    if value == "country":
        return "country"
    if value in {"city", "town", "municipality"}:
        return "city"
    if value == "state" and subdivision_code in {"CN-BJ", "CN-SH", "CN-TJ", "CN-CQ", "CN-HK", "CN-MO"}:
        return "city"
    if value in {"state", "province", "region", "county"}:
        return "administrative_area"
    if value in {"island", "islet"}:
        return "island"
    if value in {"aerodrome", "airport"} or category == "aeroway":
        return "airport"
    if facility in {"station", "halt"} and category in {"railway", "public_transport"}:
        return "train_station"
    if value in {"national_park", "nature_reserve", "protected_area"}:
        return "scenic_area"
    if value in {"hotel", "guest_house", "hostel"}:
        return "hotel"
    if value in {"restaurant", "cafe", "fast_food"}:
        return "restaurant"
    if category in {"tourism", "historic", "leisure", "natural"}:
        return "poi"
    return None


def nominatim_trip_place(item: Mapping[str, Any]) -> dict[str, Any] | None:
    """按同一规则转换表单搜索和理解工具使用的原始地点。"""
    kind = _kind(item)
    address = item.get("address") if isinstance(item.get("address"), dict) else {}
    country_code = str(address.get("country_code") or "").lower()
    osm_type = str(item.get("osm_type") or "").lower()
    osm_id = str(item.get("osm_id") or "")
    display_name = str(item.get("display_name") or "").strip()
    name = str(item.get("name") or display_name.split(",", 1)[0]).strip()
    place_id = stable_place_id_osm(osm_type, osm_id)
    if kind is None or len(country_code) != 2 or place_id is None:
        return None
    try:
        latitude = float(item["lat"])
        longitude = float(item["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not name or not display_name or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return {
        "place_id": place_id,
        "provider": "osm",
        "kind": kind,
        "name": name,
        "display_name": display_name,
        "country_code": country_code,
        "latitude": latitude,
        "longitude": longitude,
        "admin_path": [
            str(address[key])
            for key in ("country", "state", "province", "city", "county")
            if address.get(key)
        ],
    }
