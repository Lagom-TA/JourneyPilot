"""受控旅行输入使用的地点搜索。"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, HTTPException, Query

from travel_agent.planning.requirements.identity_contracts import DESTINATION_PLACE_KINDS, ITINERARY_PLACE_KINDS, ORIGIN_PLACE_KINDS, PlaceIdentity, PlaceKind
from travel_agent.integrations.places.contracts import NominatimPlaceSearchError
from travel_agent.integrations.places.nominatim import search_nominatim_raw
from travel_agent.api.schemas.places import PlaceCandidateResponse, PlaceSearchResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/places", tags=["places"])


def _kind(item: Dict[str, Any]) -> Optional[PlaceKind]:
    value = str(item.get("addresstype") or item.get("type") or "").lower()
    # Nominatim 将车站标记为 addresstype="railway" / type="station"，
    # 具体设施类型只能从 ``type`` 读取。
    facility = str(item.get("type") or "").lower()
    category = str(item.get("category") or item.get("class") or "").lower()
    address = item.get("address") if isinstance(item.get("address"), dict) else {}
    subdivision_code = str(
        address.get("ISO3166-2-lvl4")
        or address.get("ISO3166-2-lvl3")
        or ""
    ).upper()
    if value in {"country"}:
        return PlaceKind.COUNTRY
    if value in {"city", "town", "municipality"}:
        return PlaceKind.CITY
    if value == "state" and subdivision_code in {"CN-BJ", "CN-SH", "CN-TJ", "CN-CQ", "CN-HK", "CN-MO"}:
        return PlaceKind.CITY
    if value in {"state", "province", "region", "county"}:
        return PlaceKind.ADMINISTRATIVE_AREA
    if value in {"island", "islet"}:
        return PlaceKind.ISLAND
    if value in {"aerodrome", "airport"} or category == "aeroway":
        return PlaceKind.AIRPORT
    if facility in {"station", "halt"} and category in {"railway", "public_transport"}:
        return PlaceKind.TRAIN_STATION
    if value in {"national_park", "nature_reserve", "protected_area"}:
        return PlaceKind.SCENIC_AREA
    if value in {"hotel", "guest_house", "hostel"}:
        return PlaceKind.HOTEL
    if value in {"restaurant", "cafe", "fast_food"}:
        return PlaceKind.RESTAURANT
    if category in {"tourism", "historic", "leisure", "natural"}:
        return PlaceKind.POI
    return None


def _candidate(item: Dict[str, Any], *, role: str) -> Optional[PlaceCandidateResponse]:
    kind = _kind(item)
    allowed = {
        "origin": ORIGIN_PLACE_KINDS,
        "destination": DESTINATION_PLACE_KINDS,
        "itinerary_place": ITINERARY_PLACE_KINDS,
    }[role]
    if kind not in allowed:
        return None
    address = item.get("address") if isinstance(item.get("address"), dict) else {}
    country_code = str(address.get("country_code") or "").lower()
    if len(country_code) != 2:
        return None
    osm_type = str(item.get("osm_type") or "").lower()
    osm_id = str(item.get("osm_id") or "")
    if not osm_type or not osm_id:
        return None
    display_name = str(item.get("display_name") or "").strip()
    short_name = str(item.get("name") or display_name.split(",", 1)[0]).strip()
    importance = max(0.0, min(float(item.get("importance") or 0.0), 1.0))
    place = PlaceIdentity(
        place_id=f"osm:{osm_type}:{osm_id}",
        provider="osm",
        kind=kind,
        name=short_name,
        display_name=display_name,
        country_code=country_code,
        latitude=float(item["lat"]),
        longitude=float(item["lon"]),
        admin_path=[
            str(address[key])
            for key in ("country", "state", "province", "city", "county")
            if address.get(key)
        ],
    )
    return PlaceCandidateResponse(
        place=place,
        confidence=round(importance, 4),
        requires_confirmation=True,
    )


@router.get("/search", response_model=PlaceSearchResponse)
async def search_places(
    q: str = Query(min_length=1, max_length=120),
    role: Literal["origin", "destination", "itinerary_place"] = Query(),
) -> PlaceSearchResponse:
    try:
        observation = await search_nominatim_raw(q, limit=5)
    except ValueError as exc:
        # 参数非法是调用方错误，重试无效，因此返回 400 而非与 provider 故障共用 503：
        # ``?q=%20`` 能通过 ``min_length=1``，但归一化后为空。
        logger.info("地点搜索参数非法：%s", exc)
        raise HTTPException(
            status_code=400,
            detail={
                "code": "place_query_invalid",
                "message": "请输入要搜索的地点名称",
            },
        ) from exc
    except NominatimPlaceSearchError as exc:
        # 具体原因（重试耗尽 / 非 JSON / 响应形状不符）写入日志，对外统一为一个
        # 错误码：三种情况下用户的处置方式相同，都是保留输入并重试。
        logger.warning("地点搜索失败：provider %s（%s）", exc.code, exc)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "place_provider_unavailable",
                "message": "地点服务暂时不可用，请保留当前输入并重试",
            },
        ) from exc
    candidates = [
        candidate
        for item in observation.items
        if (candidate := _candidate(item, role=role)) is not None
    ]
    return PlaceSearchResponse(query=q, role=role, candidates=candidates)
