"""Integrations places search."""

from __future__ import annotations

from travel_agent.integrations.places.nominatim import lookup_nominatim_osm_ids
from travel_agent.integrations.places.normalization import normalize_nominatim_place
from travel_agent.integrations.places.overpass import search_overpass_place_ids
from typing import Any
from typing import Callable
from typing import Dict
from typing import Optional


_IDENTITY_FALLBACK_BUDGET_SECONDS = 20.0


async def _resolve_identity_inside_relation(
    entity_names: list[str],
    *,
    candidate_kind: str,
    country_code: str,
    destination_place_id: str,
    destination_latitude: Optional[float],
    destination_longitude: Optional[float],
    limit: int,
    is_concrete: Callable[[Dict[str, Any]], bool],
) -> list[Dict[str, Any]]:
    """按别名逐条解析受控 relation 内的具体实体身份，命中即停。

    一条别名一次查询：把整个别名集拼成一条 alternation、再乘上本域的多条 tag
    predicate，会超出 Overpass 解释器自己的 timeout，回来的是「provider 不可用」而
    不是「区域内没有」。Provider 连重试都用尽时结束整条 fallback——那是 provider 的
    判决，不是这条别名的判决，换个别名只会再烧一遍同一个时间片。
    """
    for alias in entity_names:
        osm_ids = await search_overpass_place_ids(
            [alias],
            kind=candidate_kind,
            destination_place_id=destination_place_id,
            destination_latitude=destination_latitude,
            destination_longitude=destination_longitude,
            limit=limit,
        )
        lookup = await lookup_nominatim_osm_ids(osm_ids)
        resolved = [
            place
            for item in lookup
            if (place := normalize_nominatim_place(item)) is not None
            and place["provider_country_code"] == country_code
            and is_concrete(place)
        ]
        if resolved:
            return resolved
    return []
