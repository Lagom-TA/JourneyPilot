"""受控旅行输入使用的地点搜索。"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, HTTPException, Query

from travel_agent.planning.requirements.identity_contracts import DESTINATION_PLACE_KINDS, ITINERARY_PLACE_KINDS, ORIGIN_PLACE_KINDS, PlaceIdentity
from travel_agent.integrations.places.contracts import NominatimPlaceSearchError
from travel_agent.integrations.places.identity import nominatim_trip_place
from travel_agent.integrations.places.nominatim import search_nominatim_raw
from travel_agent.api.schemas.places import PlaceCandidateResponse, PlaceSearchResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/places", tags=["places"])


def _candidate(item: Dict[str, Any], *, role: str) -> Optional[PlaceCandidateResponse]:
    raw_place = nominatim_trip_place(item)
    if raw_place is None:
        return None
    place = PlaceIdentity.model_validate(raw_place)
    allowed = {
        "origin": ORIGIN_PLACE_KINDS,
        "destination": DESTINATION_PLACE_KINDS,
        "itinerary_place": ITINERARY_PLACE_KINDS,
    }[role]
    if place.kind not in allowed:
        return None
    importance = max(0.0, min(float(item.get("importance") or 0.0), 1.0))
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
