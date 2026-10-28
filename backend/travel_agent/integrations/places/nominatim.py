"""Nominatim 的搜索与 OSM id 查询。"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from travel_agent.config.loader import get_settings
from travel_agent.integrations.places.contracts import NominatimPlaceSearchError
from travel_agent.integrations.places.contracts import NominatimSearchObservation
from travel_agent.integrations.places.normalization import normalize_country_code
from travel_agent.integrations.places.retry import _RATE_GATE
from travel_agent.integrations.places.retry import _send_with_retry
from travel_agent.integrations.places.normalization import _is_coordinate
from travel_agent.integrations.places.normalization import destination_focus_viewbox
from travel_agent.storage.place_search_cache import _SEARCH_CACHE
from travel_agent.storage.place_search_cache import _search_cache_digest
from typing import Any
from typing import Dict
from typing import Optional
import httpx


async def search_nominatim_raw(
    query: str,
    *,
    country_code: Optional[str] = None,
    limit: int = 5,
    focus_latitude: Optional[float] = None,
    focus_longitude: Optional[float] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> NominatimSearchObservation:
    """返回一次全球地点查询的完整有界 Provider 响应。

    所有调用 ``/search`` 的路径（intake 路由、authored-place 查询序列与
    ``global_place_search`` 工具）都经过这里，因此缓存复用也放在这里。返回结果
    自带 ``observed_at``：复用缓存时它是 Provider 生成该响应的时刻，调用方应发布
    该时间，而不是 ``now``。

    ``focus_latitude`` / ``focus_longitude`` 是受控目的地自身的 Provider 坐标。
    它们会转换成 :func:`destination_focus_viewbox`；转换只在这里做一次，持有目的地
    坐标的两个调用方（``global_place_search`` 工具与 authored-place 查询序列）因此不会
    得到不同的聚焦范围。intake 路由可以没有坐标：它正是要解析目的地的请求。

    只有半个坐标时不聚焦，避免默认聚焦到本初子午线。
    """
    normalized_query = " ".join((query or "").split())
    if not normalized_query:
        raise ValueError("query is required")
    if not 1 <= limit <= 10:
        raise ValueError("limit must be between 1 and 10")
    normalized_country = normalize_country_code(country_code)
    settings = get_settings().geocoding
    params: Dict[str, Any] = {
        "q": normalized_query,
        "format": "jsonv2",
        "addressdetails": 1,
        "namedetails": 1,
        "limit": limit,
        "accept-language": "zh-CN,zh,en",
    }
    if normalized_country is not None:
        params["countrycodes"] = normalized_country
    if _is_coordinate(focus_latitude) and _is_coordinate(focus_longitude):
        params["viewbox"] = destination_focus_viewbox(
            float(focus_latitude), float(focus_longitude)
        )
    base_url = settings.nominatim_base_url.rstrip("/")
    digest = _search_cache_digest(base_url, params)

    cached = await _SEARCH_CACHE.get(digest)
    if cached is not None:
        return cached
    owns_client = client is None
    resolved_client = client or httpx.AsyncClient(
        timeout=settings.search_timeout_seconds,
        headers={"User-Agent": settings.user_agent},
    )
    try:
        response = await _send_with_retry(
            lambda: resolved_client.get(
                f"{base_url}/search",
                params=params,
            ),
            rate_gate=_RATE_GATE,
            min_interval_seconds=settings.min_interval_seconds,
            unavailable_message="global place provider unavailable",
        )
        raw = response.json()
    except ValueError as exc:
        raise NominatimPlaceSearchError(
            "global place provider returned a non-JSON body",
            code="provider_unparseable",
        ) from exc
    finally:
        if owns_client:
            await resolved_client.aclose()
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise NominatimPlaceSearchError(
            "global place provider returned an invalid payload",
            code="provider_invalid_payload",
        )
    observation = NominatimSearchObservation(
        items=[dict(item) for item in raw],
        observed_at=datetime.now(timezone.utc),
        origin="live",
    )
    await _SEARCH_CACHE.set(digest, observation)
    return observation


async def lookup_nominatim_osm_ids(
    osm_ids: list[str],
    *,
    accept_language: Optional[str] = "zh-CN,zh,en",
    client: Optional[httpx.AsyncClient] = None,
) -> list[Dict[str, Any]]:
    """为精确的 OSM 身份读取完整地址、国家与类型事实。

    ``accept_language`` 是 Provider 自己的参数名：默认值是流水线其余部分存储地点
    时使用的身份语言；传 ``None`` 时省略该参数，由 Provider 按各地本地文字回答。
    """
    if not osm_ids:
        return []
    settings = get_settings().geocoding
    owns_client = client is None
    resolved_client = client or httpx.AsyncClient(
        timeout=settings.timeout_seconds,
        headers={"User-Agent": settings.user_agent},
    )
    params: Dict[str, Any] = {
        "osm_ids": ",".join(osm_ids),
        "format": "jsonv2",
        "addressdetails": 1,
        "namedetails": 1,
    }
    if accept_language:
        params["accept-language"] = accept_language
    try:
        response = await _send_with_retry(
            lambda: resolved_client.get(
                f"{settings.nominatim_base_url.rstrip('/')}/lookup",
                params=params,
            ),
            rate_gate=_RATE_GATE,
            min_interval_seconds=settings.min_interval_seconds,
            unavailable_message="global place identity lookup unavailable",
        )
        payload = response.json()
    except ValueError as exc:
        raise NominatimPlaceSearchError(
            "global place identity lookup returned a non-JSON body",
            code="provider_unparseable",
        ) from exc
    finally:
        if owns_client:
            await resolved_client.aclose()
    if not isinstance(payload, list) or any(
        not isinstance(item, dict) for item in payload
    ):
        raise NominatimPlaceSearchError(
            "global place identity lookup returned invalid data",
            code="provider_invalid_payload",
        )
    return [dict(item) for item in payload]
