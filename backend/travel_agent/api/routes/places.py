"""受控旅行输入使用的地点搜索。"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, HTTPException, Query

from travel_agent.planning.requirements.identity_contracts import DESTINATION_PLACE_KINDS, ITINERARY_PLACE_KINDS, ORIGIN_PLACE_KINDS, PlaceIdentity
from travel_agent.integrations.places.contracts import NominatimPlaceSearchError
from travel_agent.integrations.places.photon import photon_trip_place, search_photon_raw
from travel_agent.api.schemas.places import PlaceCandidateResponse, PlaceSearchResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/places", tags=["places"])


def _candidate(item: Dict[str, Any], *, role: str) -> Optional[PlaceCandidateResponse]:
    raw_place = photon_trip_place(item)
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
    return PlaceCandidateResponse(
        place=place,
        confidence=0.5,
        requires_confirmation=True,
    )


@router.get("/search", response_model=PlaceSearchResponse)
async def search_places(
    q: str = Query(min_length=1, max_length=120),
    role: Literal["origin", "destination", "itinerary_place"] = Query(),
) -> PlaceSearchResponse:
    try:
        observation = await search_photon_raw(q, limit=15)
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
        # 对外不暴露上游响应或用户查询，统一提示保留输入并重试。
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
    ][:5]
    return PlaceSearchResponse(query=q, role=role, candidates=candidates)
