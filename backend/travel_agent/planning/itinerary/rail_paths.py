"""为已物化的 12306 铁路段补充公共交通 Provider 的轨道几何。"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from travel_agent.planning.itinerary.models import TransportLeg
from travel_agent.planning.nodes import NODE_ITINERARY
from travel_agent.planning.research.candidates import TransportCandidate
from travel_agent.planning.research.output.transcript import (
    _successful_route_records,
    authoritative_tool_messages,
)
from travel_agent.planning.transport import RoutePathPoint, TransportMode
from travel_agent.planning.workspace import TripWorkspaceV2
from travel_agent.tools.execution import execute_tool
from travel_agent.tools.registry import get_tool_registry

logger = logging.getLogger(__name__)

_RAIL_PATH_TOOL_NAMES = frozenset({"global_route_search"})
_RAIL_MODES = frozenset({TransportMode.TRAIN, TransportMode.HIGH_SPEED_RAIL})
_12306_PROVIDER_NAMES = frozenset({"12306", "12306-train"})


def _12306_rail_candidate_ids(workspace: TripWorkspaceV2) -> set[str]:
    """只返回具有 12306 来源的长途铁路候选，排除其他铁路路线来源。"""
    candidate_ids: set[str] = set()
    for packet in workspace.recommendation_catalog.research_packets:
        sources = {source.source_record_id: source for source in packet.source_records}
        for candidate in packet.candidates:
            if (
                not isinstance(candidate, TransportCandidate)
                or candidate.transport_class != "long_distance"
                or candidate.selected_mode not in _RAIL_MODES
            ):
                continue
            if any(
                source.provider_name.strip().casefold() in _12306_PROVIDER_NAMES
                for source_id in candidate.source_record_ids
                if (source := sources.get(source_id)) is not None
            ):
                candidate_ids.add(candidate.candidate_id)
    return candidate_ids


def _path_request(leg: TransportLeg) -> Optional[dict[str, Any]]:
    """使用 12306 已确定的车站身份、坐标与时刻构建几何查询。"""
    origin = leg.from_endpoint
    destination = leg.to_endpoint
    coordinates = (
        origin.latitude,
        origin.longitude,
        destination.latitude,
        destination.longitude,
    )
    if (
        leg.departure_at is None
        or not origin.place_id
        or not destination.place_id
        or any(value is None for value in coordinates)
    ):
        return None
    return {
        "from_name": origin.name,
        "from_place_id": origin.place_id,
        "from_latitude": origin.latitude,
        "from_longitude": origin.longitude,
        "to_name": destination.name,
        "to_place_id": destination.place_id,
        "to_latitude": destination.latitude,
        "to_longitude": destination.longitude,
        "departure_time": leg.departure_at.isoformat(),
        "mode": "public_transit",
    }


def _matching_rail_path(
    envelope: Mapping[str, Any],
    leg: TransportLeg,
) -> list[RoutePathPoint]:
    """只提取端点一致且路线、分段方式都与目标铁路类别一致的非空路径。"""
    target_mode = leg.selected_mode.value
    records = _successful_route_records(authoritative_tool_messages([envelope]))
    for _route_id, (_route_envelope, route, _route_index) in records.items():
        if route.get("selected_mode") != target_mode:
            continue
        origin = route.get("from_endpoint") or {}
        destination = route.get("to_endpoint") or {}
        if (
            origin.get("place_id") != leg.from_endpoint.place_id
            or destination.get("place_id") != leg.to_endpoint.place_id
        ):
            continue
        for segment in route.get("segments") or []:
            if segment.get("mode") != target_mode:
                continue
            raw_path = segment.get("path")
            if not isinstance(raw_path, list) or len(raw_path) < 2:
                continue
            try:
                return [RoutePathPoint.model_validate(point) for point in raw_path]
            except (TypeError, ValueError):
                continue
    return []


def _request_cache_key(
    leg: TransportLeg,
    request: Mapping[str, Any],
) -> tuple[Any, ...]:
    """相同铁路类别和有向车站端点在一次补全中共享一次几何查询。"""
    return (
        leg.selected_mode.value,
        request["from_place_id"],
        request["to_place_id"],
        request["from_latitude"],
        request["from_longitude"],
        request["to_latitude"],
        request["to_longitude"],
    )


async def complete_rail_route_paths(
    workspace: TripWorkspaceV2,
    *,
    tool_context: Optional[Mapping[str, Any]] = None,
) -> TripWorkspaceV2:
    """为选中的 12306 铁路段补路径，任何几何失败都保留原行程段。"""
    candidate_ids = _12306_rail_candidate_ids(workspace)
    if not candidate_ids:
        return workspace
    candidates = workspace.recommendation_catalog.candidate_index()
    targets: list[tuple[TransportLeg, dict[str, Any]]] = []
    for leg in workspace.itinerary.transport_legs:
        candidate = candidates.get(leg.lineage.candidate_id or "")
        if (
            leg.transport_class != "long_distance"
            or leg.selected_mode not in _RAIL_MODES
            or leg.lineage.candidate_id not in candidate_ids
            or not isinstance(candidate, TransportCandidate)
            or candidate.selected_mode != leg.selected_mode
        ):
            continue
        target_segments = [
            segment for segment in leg.segments if segment.mode == leg.selected_mode
        ]
        if len(target_segments) != 1 or target_segments[0].path:
            continue
        request = _path_request(leg)
        if request is not None:
            targets.append((leg, request))
    if not targets:
        return workspace
    try:
        if not get_tool_registry().has_tool("global_route_search"):
            return workspace
    except Exception:
        logger.warning("[rail_path] 路线工具注册表不可用，保留空铁路路径", exc_info=True)
        return workspace

    context = dict(tool_context or {})
    path_cache: dict[tuple[Any, ...], list[RoutePathPoint]] = {}
    for leg, request in targets:
        key = _request_cache_key(leg, request)
        if key in path_cache:
            continue
        try:
            envelope = await execute_tool(
                "global_route_search",
                request,
                allowed_tool_names=_RAIL_PATH_TOOL_NAMES,
                max_retries=0,
                node_name=NODE_ITINERARY,
                activation_source="rail_route_path_completion",
                allow_fallback=False,
                **context,
            )
            path_cache[key] = (
                _matching_rail_path(envelope, leg)
                if isinstance(envelope, Mapping)
                else []
            )
        except Exception:
            path_cache[key] = []
            logger.warning(
                "[rail_path] 铁路几何查询失败 leg=%s，保留空路径",
                leg.transport_leg_id,
                exc_info=True,
            )

    updated_legs: list[TransportLeg] = []
    changed = False
    requests_by_leg = {leg.transport_leg_id: request for leg, request in targets}
    for leg in workspace.itinerary.transport_legs:
        request = requests_by_leg.get(leg.transport_leg_id)
        if request is None:
            updated_legs.append(leg)
            continue
        path = path_cache.get(_request_cache_key(leg, request), [])
        if not path:
            updated_legs.append(leg)
            continue
        updated_legs.append(
            leg.model_copy(
                update={
                    "segments": [
                        segment.model_copy(update={"path": path})
                        if segment.mode == leg.selected_mode
                        else segment
                        for segment in leg.segments
                    ]
                }
            )
        )
        changed = True
    if not changed:
        return workspace
    return workspace.model_copy(
        update={
            "itinerary": workspace.itinerary.model_copy(
                update={"transport_legs": updated_legs}
            )
        }
    )
