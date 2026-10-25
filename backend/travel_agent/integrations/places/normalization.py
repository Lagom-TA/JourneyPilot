"""Integrations places normalization."""

from __future__ import annotations

from travel_agent.integrations.place_identity import stable_place_id_osm
from travel_agent.integrations.places.taxonomy import is_administrative_provider_type
from travel_agent.integrations.places.taxonomy import (
    provider_place_type_matches_candidate_kind,
)
from typing import Any
from typing import Callable
from typing import Dict
from typing import Optional
import logging
import re

import math


logger = logging.getLogger(__name__)


_COUNTRY_CODE = re.compile(r"^[a-z]{2}$")


_OSM_RELATION_PLACE_ID = re.compile(r"^osm:relation:(?P<relation_id>[1-9]\d*)$")


_DINING_PLACE_TYPES = {
    "amenity;restaurant",
    "amenity;cafe",
    "amenity;fast_food",
    "amenity;bar",
    "amenity;pub",
    "amenity;food_court",
}


_GENERIC_DINING_NAMES = {
    "ramen",
    "restaurant",
    "cafe",
    "bar",
    "pub",
    "ラーメン",
    "拉面",
    "拉麵",
    "餐厅",
    "餐廳",
}


_DINING_COLLECTION_TOKENS = (
    "food court",
    "kokugikan",
    "ramen street",
    "market",
    "国技館",
    "横丁",
    "市場",
    "市场",
    "美食街",
)


_GENERIC_LODGING_NAMES = {
    "hotel",
    "hôtel",
    "hostel",
    "motel",
    "inn",
    "resort",
    "apartment",
    "apartments",
    "guest house",
    "guesthouse",
    "guest-house",
    "b&b",
    "bed and breakfast",
    "pension",
    "ryokan",
    "ホテル",
    "旅館",
    "ゲストハウス",
    "民宿",
    "酒店",
    "飯店",
    "饭店",
    "宾馆",
    "賓館",
    "旅馆",
    "招待所",
}


def normalize_country_code(value: Optional[str]) -> Optional[str]:
    normalized = (value or "").strip().casefold() or None
    if normalized is not None and not _COUNTRY_CODE.fullmatch(normalized):
        raise ValueError("country_code must be a two-letter ISO 3166-1 code")
    return normalized


_DISPLAY_NAME_PREFERENCE = ("name:zh", "name:zh-Hans")


def _preferred_display_name(namedetails: Dict[str, Any], provider_name: str) -> str:
    """Pick the name to show a Chinese-reading traveller, from what the provider has."""

    for key in _DISPLAY_NAME_PREFERENCE:
        candidate = str(namedetails.get(key) or "").strip()
        if candidate:
            return candidate
    return provider_name


def normalize_nominatim_place(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Project one provider item without inventing identity or category fields."""
    address = item.get("address") if isinstance(item.get("address"), dict) else {}
    country_code = str(address.get("country_code") or "").strip().casefold()
    osm_type = str(item.get("osm_type") or "").strip().casefold()
    osm_id = str(item.get("osm_id") or "").strip()
    display_name = str(item.get("display_name") or "").strip()
    namedetails = (
        item.get("namedetails") if isinstance(item.get("namedetails"), dict) else {}
    )
    provider_name = str(
        item.get("name") or namedetails.get("name") or display_name.split(",", 1)[0]
    ).strip()

    name = _preferred_display_name(namedetails, provider_name)
    if (
        not _COUNTRY_CODE.fullmatch(country_code)
        or osm_type not in {"node", "way", "relation"}
        or not osm_id
        or not display_name
        or not name
    ):
        return None
    provider_types = list(
        dict.fromkeys(
            value
            for value in (
                str(item.get("category") or item.get("class") or "").strip(),
                str(item.get("type") or "").strip(),
                str(item.get("addresstype") or "").strip(),
            )
            if value
        )
    )
    if not provider_types:
        return None
    try:
        latitude = float(item["lat"])
        longitude = float(item["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    aliases = list(
        dict.fromkeys(
            alias
            for alias in (
                provider_name,
                *(
                    str(namedetails.get(key) or "").strip()
                    for key in (
                        "name:en",
                        "name:ja",
                        "name:zh",
                        "name:ja-Hira",
                        "official_name",
                        "brand",
                        "name",
                    )
                ),
            )
            if alias and alias.casefold() != name.casefold()
        )
    )
    place_id = stable_place_id_osm(osm_type, osm_id)
    if place_id is None:
        return None
    place = {
        "place_id": place_id,
        "provider": "nominatim",
        "provider_place_type": ";".join(provider_types),
        "provider_country_code": country_code,
        "name": name,
        "address": display_name,
        "latitude": latitude,
        "longitude": longitude,
    }
    if aliases:
        place["aliases"] = aliases[:6]
    return place


def is_concrete_dining_place(place: Dict[str, Any]) -> bool:
    """Reject category labels and multi-vendor collections as Dining entities."""
    name = " ".join(str(place.get("name") or "").split())
    lowered = name.casefold()
    return bool(
        place.get("provider_place_type") in _DINING_PLACE_TYPES
        and place.get("provider_place_type") != "amenity;food_court"
        and lowered not in _GENERIC_DINING_NAMES
        and not any(token in lowered for token in _DINING_COLLECTION_TOKENS)
    )


def is_concrete_lodging_place(place: Dict[str, Any]) -> bool:
    """Reject category labels and nameless OSM records as Lodging entities.

    The lodging sibling of ``is_concrete_dining_place``.  The provider-domain
    boundary stays the single admission authority
    (``provider_place_type_matches_candidate_kind``); this adds the concreteness
    dimension a bound property identity needs.  An OSM lodging record with no
    ``name`` tag normalizes its name from the first ``display_name`` component —
    a house number such as "16" — which is not a property anyone can book.
    """
    if not provider_place_type_matches_candidate_kind(
        str(place.get("provider_place_type") or ""),
        "lodging",
    ):
        return False
    name = " ".join(str(place.get("name") or "").split())
    if not any(character.isalpha() for character in name):
        return False
    return name.casefold() not in _GENERIC_LODGING_NAMES


def is_concrete_visit_place(place: Dict[str, Any]) -> bool:
    """Reject areas and nameless records as Visit entities.

    Visit 的具体性判据与 Visit 准入同哲学：排除法。这个域装得下博物馆、寺庙、公园、
    观景台、商场和 amap 的中文类别，写 allowlist 会把没列到的真实场馆、以及测试里
    ``attraction`` / ``商业街`` 一类裸类别全判假；能确定的只有反面——一条 provider
    类型说自己是行政区划或边界时，返回的是一片区域，不是一个能安排进某一天的停留点。
    "museum in <短名>" 这类区域内查询正是靠这条把目的地自身的边界记录挡在外面。
    """
    if not provider_place_type_matches_candidate_kind(
        str(place.get("provider_place_type") or ""),
        "visit",
    ):
        return False
    if is_administrative_provider_type(str(place.get("provider_place_type") or "")):
        return False
    name = " ".join(str(place.get("name") or "").split())
    return any(character.isalpha() for character in name)


_CONCRETE_PLACE_FILTERS: Dict[str, Callable[[Dict[str, Any]], bool]] = {
    "dining": is_concrete_dining_place,
    "visit": is_concrete_visit_place,
}


_DESTINATION_FOCUS_HALF_SIZE_KM = 15.0


_KM_PER_DEGREE_LATITUDE = 2 * math.pi * 6371.0088 / 360


def _is_coordinate(value: Any) -> bool:
    """Whether a value is a usable coordinate. ``True`` is an ``int``, not a point."""

    return isinstance(value, (int, float)) and not isinstance(value, bool)


def destination_focus_viewbox(latitude: float, longitude: float) -> str:
    """The Nominatim ``viewbox`` a destination's own point defines.

    A *preference*, never a filter: the caller must not pair it with
    ``bounded=1``.  Soft is the whole point — a query that names a place outside
    the box still resolves to that place (日光東照宮 120km north and 箱根神社 80km
    south-west return byte-identical answers with and without it), while a query
    that names no place stops being answered from the far edge of a prefecture.
    Making it a filter would trade the defect for a worse one: a named stop the
    traveller asked for by name would become unresolvable.

    The box is square in kilometres, not in degrees, so it does not stretch
    east-west as the destination moves away from the equator.
    """

    latitude_span = _DESTINATION_FOCUS_HALF_SIZE_KM / _KM_PER_DEGREE_LATITUDE

    parallel_km = _KM_PER_DEGREE_LATITUDE * math.cos(math.radians(latitude))
    longitude_span = (
        180.0
        if parallel_km <= 0
        else min(180.0, _DESTINATION_FOCUS_HALF_SIZE_KM / parallel_km)
    )
    return (
        f"{longitude - longitude_span:.6f},{latitude - latitude_span:.6f},"
        f"{longitude + longitude_span:.6f},{latitude + latitude_span:.6f}"
    )
