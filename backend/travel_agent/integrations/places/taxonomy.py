"""Integrations places taxonomy."""

from __future__ import annotations

import re


_DINING_PROVIDER_TYPE_MARKERS = (
    "餐饮服务",
    "餐厅",
    "餐馆",
    "饮食店",
    "咖啡",
    "酒吧",
    "居酒屋",
    "料理店",
    "食堂",
    "レストラン",
    "カフェ",
    "飲食店",
)


_DINING_PROVIDER_TYPE_TOKENS = {
    "restaurant",
    "cafe",
    "coffee",
    "bar",
    "pub",
    "izakaya",
    "fast_food",
    "food_court",
    "food_stall",
}


_LODGING_PROVIDER_TYPE_MARKERS = (
    "酒店",
    "旅馆",
    "旅館",
    "民宿",
)


_LODGING_PROVIDER_TYPE_TOKENS = {
    "hotel",
    "hostel",
    "guest_house",
    "motel",
    "resort",
    "apartment",
}


_ADMINISTRATIVE_PROVIDER_TYPE_MARKERS = (
    "行政区",
    "行政地名",
    "省级地名",
    "市级地名",
    "区县级地名",
    "乡镇级地名",
    "村庄级地名",
)


_ADMINISTRATIVE_PROVIDER_TYPE_TOKENS = {
    "boundary",
    "administrative",
    "political",
    "postcode",
    "city",
    "town",
    "village",
    "hamlet",
    "suburb",
    "quarter",
    "neighbourhood",
    "neighborhood",
    "borough",
    "county",
    "state",
    "province",
    "prefecture",
    "region",
    "municipality",
    "country",
    "continent",
}


def _is_dining_provider_type(value: str) -> bool:
    normalized = " ".join(value.split()).casefold()
    if any(marker.casefold() in normalized for marker in _DINING_PROVIDER_TYPE_MARKERS):
        return True
    tokens = {
        token
        for token in re.split(r"[^a-z0-9_]+", normalized.replace("-", "_"))
        if token
    }
    return bool(tokens & _DINING_PROVIDER_TYPE_TOKENS)


def _is_lodging_provider_type(value: str) -> bool:
    normalized = " ".join(value.split()).casefold()
    if any(
        marker.casefold() in normalized for marker in _LODGING_PROVIDER_TYPE_MARKERS
    ):
        return True
    tokens = {
        token
        for token in re.split(r"[^a-z0-9_]+", normalized.replace("-", "_"))
        if token
    }
    return bool(tokens & _LODGING_PROVIDER_TYPE_TOKENS)


def is_administrative_provider_type(value: str) -> bool:
    """一条 provider 类型是否描述行政区划/边界/纯地名，而不是一个具体地点。"""
    normalized = " ".join(value.split()).casefold()
    if any(
        marker.casefold() in normalized
        for marker in _ADMINISTRATIVE_PROVIDER_TYPE_MARKERS
    ):
        return True
    tokens = {
        token
        for token in re.split(r"[^a-z0-9_]+", normalized.replace("-", "_"))
        if token
    }
    return bool(tokens & _ADMINISTRATIVE_PROVIDER_TYPE_TOKENS)


def provider_place_type_matches_candidate_kind(
    value: str,
    candidate_kind: str,
) -> bool:
    """Apply the same provider-domain boundary before and during admission."""
    if candidate_kind == "dining":
        return _is_dining_provider_type(value)
    if candidate_kind == "lodging":
        return _is_lodging_provider_type(value)
    if candidate_kind == "visit":
        return not (_is_dining_provider_type(value) or _is_lodging_provider_type(value))
    return False
