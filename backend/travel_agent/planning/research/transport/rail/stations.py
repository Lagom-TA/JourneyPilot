from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional

from travel_agent.planning.itinerary.place_resolution import (
    AuthoredPlaceScope,
    AuthoredPlaceToolAccess,
    resolve_station_point,
)
from travel_agent.planning.research.transport.scope import _NODE_NAME
from travel_agent.tools.execution import execute_tool
from travel_agent.tools.registry import get_tool_registry

logger = logging.getLogger(__name__)


_STATION_POINT_TOOL_NAMES = frozenset({"maps_text_search", "maps_search_detail"})


def _rail_station_tool_access(tool_context: Dict[str, Any]) -> AuthoredPlaceToolAccess:
    """把车站定位能力绑定到本次运行受审计的工具入口。"""

    async def execute(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return await execute_tool(
            tool_name,
            arguments,
            allowed_tool_names=_STATION_POINT_TOOL_NAMES,
            node_name=_NODE_NAME,
            activation_source="rail_station_point",
            allow_fallback=False,
            **tool_context,
        )

    def has_tool(tool_name: str) -> bool:
        return get_tool_registry().has_tool(tool_name)

    return AuthoredPlaceToolAccess(execute=execute, has_tool=has_tool)


async def _locate_rail_station(
    *,
    telecode: str,
    station_name: str,
    city: str,
    city_identity: Mapping[str, Any],
    tool_context: Dict[str, Any],
    point_cache: Dict[str, Optional[tuple[float, float]]],
) -> Optional[tuple[float, float]]:
    """返回 12306 车站的坐标，用于计算到首个停留点的接驳路线。"""
    code = str(telecode or "").strip().upper()
    if not code or not str(station_name or "").strip():
        return None
    if code in point_cache:
        return point_cache[code]
    latitude = city_identity.get("latitude")
    longitude = city_identity.get("longitude")
    scope = AuthoredPlaceScope(
        country_code=str(city_identity.get("country_code") or "").strip().casefold()
        or None,
        destination_place_id=str(city_identity.get("place_id") or "").strip() or None,
        latitude=float(latitude) if isinstance(latitude, (int, float)) else None,
        longitude=float(longitude) if isinstance(longitude, (int, float)) else None,
    )
    try:
        point = await resolve_station_point(
            station_name=str(station_name),
            city=str(city),
            scope=scope,
            tools=_rail_station_tool_access(tool_context),
        )
    except Exception:
        logger.warning(
            "[transport_researcher] station point lookup failed telecode=%s name=%s",
            code,
            station_name,
            exc_info=True,
        )
        point = None
    if point is None:
        logger.warning(
            "[transport_researcher] no provider could place station %s (%s); "
            "its local connector stays authored",
            station_name,
            code,
        )
    point_cache[code] = point
    return point
