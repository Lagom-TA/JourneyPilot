from __future__ import annotations

from dataclasses import dataclass
from travel_agent.integrations.place_identity import stable_place_id_amap_poi
from travel_agent.integrations.places.contracts import NominatimPlaceSearchError
from travel_agent.integrations.places.nominatim import lookup_nominatim_osm_ids
from travel_agent.integrations.places.nominatim import search_nominatim_raw
from travel_agent.integrations.places.normalization import is_concrete_dining_place
from travel_agent.integrations.places.normalization import normalize_country_code
from travel_agent.integrations.places.normalization import normalize_nominatim_place
from travel_agent.integrations.places.overpass import search_overpass_place_ids
from travel_agent.planning.requirements.destination_scope import is_within_destination
from travel_agent.tools.governance import ToolExecutionStatus
from travel_agent.tools.governance import is_tool_execution_envelope
from travel_agent.utils.coordinates import amap_location_to_wgs84
from typing import Any
from typing import Awaitable
from typing import Callable
from typing import Dict
from typing import List
from typing import Mapping
from typing import Optional
import logging
import re


logger = logging.getLogger(__name__)


_AMAP_TEXT_SEARCH = "maps_text_search"


_AMAP_SEARCH_DETAIL = "maps_search_detail"


_AMAP_RECORDS_PER_ALIAS = 3


_OSM_ALIAS_QUERIES = 3


_BRANCH_SUFFIXES = (
    "総本店",
    "本店",
    "支店",
    "分店",
    "总店",
    "總店",
    "Honten",
    "honten",
    "Main Store",
    "Main Branch",
)


_BRANCH_PARENTHETICAL = re.compile(r"[（(][^（()）]*[)）]\s*$")


@dataclass(frozen=True)
class AuthoredPlaceToolAccess:
    """撰写地点定位使用的受审计工具入口。

    ``execute`` 绑定调用方运行上下文中的 ``tools.execution.execute_tool``，
    由它应用 Tool Gateway 白名单、Provider 快照缓存、调研时间窗，并写入
    ``tool_execution_audits``；返回 ToolExecutionEnvelope，而不是 Provider 原始 dict。

    ``has_tool`` 由调用方回答某个工具在当前部署中是否存在。定位前先询问，
    避免对未注册的工具逐个别名重试并记录 Provider 失败。
    """

    execute: Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]
    has_tool: Callable[[str], bool]


@dataclass(frozen=True)
class AuthoredPlaceScope:
    """撰写条目定位时使用的受控目的地范围。"""

    country_code: Optional[str] = None
    destination_place_id: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


def _normalized(value: Optional[str]) -> str:
    return " ".join(str(value or "").split())


def _search_aliases(local_name: str, name: str) -> List[str]:
    """返回一个条目的有限别名集合，最具体的在前。"""
    values = [
        local_name,
        name,
    ]
    return list(
        dict.fromkeys(
            alias for alias in (_normalized(value) for value in values) if alias
        )
    )[:4]


def _brand_segment(value: str) -> str:
    """返回含空格的本地语言店名前导片段，即品牌部分。

    该片段只用于校验分店身份，不能单独作为搜索别名，否则可能绑定到另一家分店。
    只有本地语言名称按空格切分；罗马化名称的首词通常是普通短词，会匹配到无关地点。
    """
    normalized = _normalized(value)
    if normalized.isascii():
        return ""
    head = normalized.split(" ")[0]
    return head if len(head) >= 2 and head != normalized else ""


def _osm_recall_aliases(local_name: str, name: str) -> List[str]:
    """返回 OSM 查询使用的别名集合，用于匹配结构化的名称标签。

    去掉空格的写法保留完整店名，分店限定词与末尾片段在同一目的地内也不会丢失。
    按具体程度排序：每个别名对应一次 Overpass 查询，先命中的结果被采用。
    """
    conservative = _search_aliases(local_name, name)
    local = _normalized(local_name)
    widened = [
        local,
        local.replace(" ", ""),
        *conservative,
    ]
    return list(dict.fromkeys(alias for alias in widened if alias))[:_OSM_ALIAS_QUERIES]


def _nominatim_queries(
    local_name: str, name: str, city: str, address: str
) -> List[str]:
    """生成查询措辞，从本地名称开始，逐步收窄到纯名称。"""
    candidates = [
        f"{local_name} {address}",
        f"{local_name} {city}",
        local_name,
        local_name.replace(" ", ""),
        f"{name} {city}",
        name,
    ]
    return list(
        dict.fromkeys(
            query for query in (_normalized(value) for value in candidates) if query
        )
    )


def _within_destination(place: Dict[str, Any], scope: AuthoredPlaceScope) -> bool:
    """判断 Provider 返回的地点是否足够接近目的地。

    距离规则来自 ``planning/requirements/destination_scope.py``。缺少可用坐标时在此直接
    拒绝：本函数的职责是把撰写名称解析成有坐标的停留点，之后仍可尝试其他
    Provider；共享的判定函数对无法回答的坐标对更宽松，因此这里显式检查。
    """
    if scope.latitude is None or scope.longitude is None:
        return True
    latitude, longitude = place.get("latitude"), place.get("longitude")
    if not isinstance(latitude, (int, float)) or not isinstance(
        longitude, (int, float)
    ):
        return False
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        return False
    return is_within_destination(
        latitude,
        longitude,
        scope.latitude,
        scope.longitude,
    )


def _accepts(
    place: Dict[str, Any],
    *,
    kind: str,
    country_code: Optional[str],
    scope: Optional[AuthoredPlaceScope] = None,
) -> bool:
    if country_code is not None and place["provider_country_code"] != country_code:
        return False
    if scope is not None and not _within_destination(place, scope):
        return False
    if kind == "dining":
        return is_concrete_dining_place(place)
    return True


async def _resolve_via_nominatim(
    *,
    local_name: str,
    name: str,
    city: str,
    address: str,
    kind: str,
    country_code: Optional[str],
    scope: AuthoredPlaceScope,
) -> Optional[Dict[str, Any]]:
    for query in _nominatim_queries(local_name, name, city, address):
        try:
            observation = await search_nominatim_raw(
                query,
                country_code=country_code,
                limit=5,
                focus_latitude=scope.latitude,
                focus_longitude=scope.longitude,
            )
        except (NominatimPlaceSearchError, ValueError) as exc:
            logger.warning(
                "authored place nominatim lookup unavailable query=%r: %s", query, exc
            )
            continue
        for item in observation.items:
            place = normalize_nominatim_place(item)
            if (
                place is not None
                and _matches_requested_branch(local_name, name, str(place["name"]))
                and _accepts(place, kind=kind, country_code=country_code, scope=scope)
            ):
                return place
    return None


def _provider_payload(
    envelope: Any, *, tool_name: str, alias: str
) -> Optional[Mapping[str, Any]]:
    """返回 Tool Gateway 信封中 Provider 自己的应答。

    被拦截、失败或超时的调用仍是格式完整的信封，只是没有 ``sanitized_result``。
    把信封本身当作应答，会把这类情况误判为「Provider 表示没有该地点」。
    """
    if not is_tool_execution_envelope(envelope):
        raise TypeError(
            f"authored place resolution expects a ToolExecutionEnvelope from {tool_name}"
        )
    if envelope.get("status") != ToolExecutionStatus.SUCCESS.value:
        logger.warning(
            "authored place amap lookup unavailable tool=%s alias=%r status=%s: %s",
            tool_name,
            alias,
            envelope.get("status"),
            envelope.get("error") or envelope.get("result_summary"),
        )
        return None
    payload = envelope.get("sanitized_result")
    return payload if isinstance(payload, Mapping) else None


def _amap_records(result: Any) -> List[Mapping[str, Any]]:
    if not isinstance(result, Mapping) or not result.get("success"):
        return []
    records = result.get("results")
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, Mapping)]


def _amap_point(result: Any) -> tuple[Optional[float], Optional[float]]:
    """读取一次详情查询返回的坐标。"""
    if not isinstance(result, Mapping):
        return None, None
    return amap_location_to_wgs84(result.get("location"))


def _names_the_same_place(alias: str, poi_name: str) -> bool:
    """判断 amap POI 是否是请求的地点，而不是附近地点。

    amap 按相关度排序，无法匹配时仍会返回附近的餐厅。把其中之一绑定到撰写
    条目，会在计划名称下交付另一个地点。
    """
    left, right = (_identity_name(value) for value in (alias, poi_name))
    return left in right or right in left


def _identity_name(value: str) -> str:
    return re.sub(r"[\s（()）·・]", "", value.casefold())


def _matches_requested_branch(local_name: str, name: str, provider_name: str) -> bool:
    """仅按品牌召回的查询不能抹掉撰写条目的分店身份。"""
    provider = _identity_name(provider_name)

    for requested in dict.fromkeys((local_name, name)):
        qualifier = _BRANCH_PARENTHETICAL.search(requested)
        if qualifier is not None:
            branch = _identity_name(qualifier.group(0))

            if branch.endswith("店"):
                branch = branch[:-1]
            return bool(branch) and branch in provider
        if any(
            requested.endswith(suffix) for suffix in _BRANCH_SUFFIXES
        ) or _brand_segment(requested):
            return _identity_name(requested) in provider
    return True


async def _resolve_via_amap(
    *,
    local_name: str,
    name: str,
    city: str,
    scope: AuthoredPlaceScope,
    tools: AuthoredPlaceToolAccess,
) -> Optional[Dict[str, Any]]:
    if not tools.has_tool(_AMAP_TEXT_SEARCH) or not tools.has_tool(_AMAP_SEARCH_DETAIL):
        return None
    for alias in _search_aliases(local_name, name):
        search = _provider_payload(
            await tools.execute(_AMAP_TEXT_SEARCH, {"keywords": alias, "city": city}),
            tool_name=_AMAP_TEXT_SEARCH,
            alias=alias,
        )
        for record in _amap_records(search)[:_AMAP_RECORDS_PER_ALIAS]:
            poi_id = _normalized(record.get("id"))
            poi_name = _normalized(record.get("name"))
            place_id = stable_place_id_amap_poi(poi_id)
            if place_id is None or not poi_name:
                continue
            if not _names_the_same_place(
                alias, poi_name
            ) or not _matches_requested_branch(local_name, name, poi_name):
                continue
            latitude, longitude = record.get("latitude"), record.get("longitude")
            if not isinstance(latitude, float) or not isinstance(longitude, float):
                latitude, longitude = _amap_point(
                    _provider_payload(
                        await tools.execute(_AMAP_SEARCH_DETAIL, {"id": poi_id}),
                        tool_name=_AMAP_SEARCH_DETAIL,
                        alias=alias,
                    )
                )
            if latitude is None or longitude is None:
                continue
            candidate = {
                "place_id": place_id,
                "provider": "amap",
                "provider_place_type": _normalized(record.get("typecode")),
                "provider_country_code": "cn",
                "name": poi_name,
                "address": _normalized(record.get("address")) or poi_name,
                "latitude": latitude,
                "longitude": longitude,
            }
            if not _within_destination(candidate, scope):
                continue
            return candidate
    return None


async def _resolve_via_overpass(
    *,
    local_name: str,
    name: str,
    kind: str,
    scope: AuthoredPlaceScope,
) -> Optional[Dict[str, Any]]:
    if scope.destination_place_id is None:
        return None
    for alias in _osm_recall_aliases(local_name, name):
        try:
            osm_ids = await search_overpass_place_ids(
                [alias],
                kind=kind,
                destination_place_id=scope.destination_place_id,
                destination_latitude=scope.latitude,
                destination_longitude=scope.longitude,
                limit=5,
            )
            items = await lookup_nominatim_osm_ids(osm_ids)
        except (NominatimPlaceSearchError, ValueError) as exc:
            logger.warning(
                "authored place overpass lookup unavailable alias=%r: %s", alias, exc
            )
            continue
        for item in items:
            place = normalize_nominatim_place(item)
            if (
                place is not None
                and _matches_requested_branch(local_name, name, str(place["name"]))
                and _accepts(
                    place, kind=kind, country_code=scope.country_code, scope=scope
                )
            ):
                return place
    return None


async def resolve_authored_place(
    *,
    name: str,
    local_name: str,
    city: str,
    address: str,
    kind: str,
    scope: AuthoredPlaceScope,
    tools: AuthoredPlaceToolAccess,
) -> Optional[Dict[str, Any]]:
    """定位一个撰写地点；没有 Provider 能识别时返回 None。

    返回规范化地点：稳定的 ``place_id``、WGS-84 坐标与 Provider 原始地址行。

    ``tools`` 是调用方的受审计工具入口；国内分支的 Provider 调用都经过它。
    """
    if kind not in {"visit", "dining"}:
        raise ValueError(f"unsupported authored place kind: {kind}")
    country_code = normalize_country_code(scope.country_code)
    normalized_local = _normalized(local_name)
    normalized_name = _normalized(name)
    normalized_city = _normalized(city)

    if country_code == "cn":
        try:
            place = await _resolve_via_amap(
                local_name=normalized_local,
                name=normalized_name,
                city=normalized_city,
                scope=scope,
                tools=tools,
            )
        except Exception:
            logger.warning(
                "authored place amap lookup failed name=%s",
                normalized_name,
                exc_info=True,
            )
            place = None
        if place is not None:
            return place

        return await _resolve_via_nominatim(
            local_name=normalized_local,
            name=normalized_name,
            city=normalized_city,
            address=_normalized(address),
            kind=kind,
            country_code=country_code,
            scope=scope,
        )

    place = await _resolve_via_nominatim(
        local_name=normalized_local,
        name=normalized_name,
        city=normalized_city,
        address=_normalized(address),
        kind=kind,
        country_code=country_code,
        scope=scope,
    )
    if place is not None:
        return place

    return await _resolve_via_overpass(
        local_name=normalized_local,
        name=normalized_name,
        kind=kind,
        scope=AuthoredPlaceScope(
            country_code=country_code,
            destination_place_id=scope.destination_place_id,
            latitude=scope.latitude,
            longitude=scope.longitude,
        ),
    )


async def resolve_station_point(
    *,
    station_name: str,
    city: str,
    scope: AuthoredPlaceScope,
    tools: AuthoredPlaceToolAccess,
) -> Optional[tuple[float, float]]:
    """在地图上定位铁路车站，但不采用 Provider 的地点身份。

    12306 车站已有稳定身份（电报码），长途腿、落位骨架与接驳缺口都以
    ``12306:{telecode}`` 指代它，但车站没有坐标；缺少一端坐标的接驳无法交给
    路线 Provider，只能按撰写时长处理。

    因此这里复用 :func:`resolve_authored_place` 的定位流程，但不返回 Provider
    的 ``place_id``：改用 ``amap:poi:…`` 会改变上游以电报码标识的端点，接驳
    会因端点不匹配而无法匹配缺口。

    车站名称不是品牌：amap 与 OSM 都按带「站」的写法索引，因此该写法优先作为
    查询别名。
    """
    country_code = normalize_country_code(scope.country_code)
    signed = _normalized(f"{_normalized(station_name)}站")
    bare = _normalized(station_name)
    if not bare:
        return None
    place: Optional[Dict[str, Any]] = None
    if country_code == "cn":
        try:
            place = await _resolve_via_amap(
                local_name=signed,
                name=bare,
                city=_normalized(city),
                scope=scope,
                tools=tools,
            )
        except Exception:
            logger.warning(
                "station point amap lookup failed station=%s", bare, exc_info=True
            )
            place = None
    if place is None:
        place = await _resolve_via_nominatim(
            local_name=signed,
            name=bare,
            city=_normalized(city),
            address="",
            kind="station",
            country_code=country_code,
            scope=scope,
        )
    if place is None:
        return None
    logger.info(
        "station point located station=%s provider=%s under=%r",
        bare,
        place.get("provider"),
        place.get("name"),
    )
    return float(place["latitude"]), float(place["longitude"])


def authored_place_scopes(
    controlled_trip_identity: Any,
) -> Dict[str, AuthoredPlaceScope]:
    """把每个受控目的地的 place id 映射到定位范围。"""
    destinations = (
        controlled_trip_identity.get("destinations")
        if isinstance(controlled_trip_identity, Mapping)
        else None
    )
    scopes: Dict[str, AuthoredPlaceScope] = {}
    for item in destinations or []:
        if not isinstance(item, Mapping):
            continue
        place_id = _normalized(item.get("place_id"))
        if not place_id:
            continue
        latitude = item.get("latitude")
        longitude = item.get("longitude")
        scopes[place_id] = AuthoredPlaceScope(
            country_code=_normalized(item.get("country_code")).casefold() or None,
            destination_place_id=place_id,
            latitude=float(latitude) if isinstance(latitude, (int, float)) else None,
            longitude=float(longitude) if isinstance(longitude, (int, float)) else None,
        )
    return scopes
