"""Nominatim 结果的归一化与具体性判断。"""

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
    """从 Provider 提供的名称中选出面向中文读者的展示名。"""

    for key in _DISPLAY_NAME_PREFERENCE:
        candidate = str(namedetails.get(key) or "").strip()
        if candidate:
            return candidate
    return provider_name


def normalize_nominatim_place(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """投影一条 Provider 结果，不自行生成身份或类别字段。"""
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
    """拒绝类别标签与多商户集合作为 Dining 实体。"""
    name = " ".join(str(place.get("name") or "").split())
    lowered = name.casefold()
    return bool(
        place.get("provider_place_type") in _DINING_PLACE_TYPES
        and place.get("provider_place_type") != "amenity;food_court"
        and lowered not in _GENERIC_DINING_NAMES
        and not any(token in lowered for token in _DINING_COLLECTION_TOKENS)
    )


def is_concrete_lodging_place(place: Dict[str, Any]) -> bool:
    """拒绝类别标签与无名称的 OSM 记录作为 Lodging 实体。

    这是 ``is_concrete_dining_place`` 的住宿侧对应实现。Provider 类型边界统一由
    ``provider_place_type_matches_candidate_kind`` 判断；这里补充绑定住宿身份所需的
    具体性维度。没有 ``name`` 标签的 OSM 住宿记录会从 ``display_name`` 的第一段
    取名称，可能得到 "16" 这样的门牌号，无法作为可预订的住宿。
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
    """拒绝区域与无名称记录作为 Visit 实体。

    Visit 的具体性判断使用排除法：这个域包含博物馆、寺庙、公园、观景台、商场与
    amap 的中文类别，写 allowlist 会漏掉未列出的真实场馆；能确定的是反面——当
    Provider 类型表明自己是行政区划或边界时，返回的是一片区域，而不是可安排进
    某一天的停留点。"museum in <短名>" 这类区域内查询正因此把目的地自身的边界
    记录排除在外。
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
    """判断一个值是否是可用的坐标；``True`` 是 int，不是坐标。"""

    return isinstance(value, (int, float)) and not isinstance(value, bool)


def destination_focus_viewbox(latitude: float, longitude: float) -> str:
    """目的地坐标定义的 Nominatim ``viewbox``。

    这是偏好范围，不是过滤器：调用方不能同时传 ``bounded=1``。它只提高区域内
    查询的排序，不排除区域外的明确地名；若改成过滤器，用户按名称指定的地点会
    变得无法解析。

    范围按公里计算而不是按度数，因此目的地远离赤道时不会在东西方向被拉长。
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
