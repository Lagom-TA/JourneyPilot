from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.itinerary.draft import (
    _SERVER_OWNED_PLACE_FIELDS,
    AuthoredPlaceBase,
    ItineraryCompositionDraft,
    authored_place_key,
    authored_places,
    map_authored_places,
)
from travel_agent.planning.nodes import NODE_ITINERARY
from travel_agent.planning.tool_context import build_tool_context_from_state
from travel_agent.runtime.operations import ModelWindowClosed, await_model_operation
from travel_agent.planning.itinerary.place_resolution import (
    AuthoredPlaceScope,
    AuthoredPlaceToolAccess,
    authored_place_scopes,
    resolve_authored_place,
)
from travel_agent.tools.execution import execute_tool
from travel_agent.tools.registry import get_tool_registry

logger = logging.getLogger(__name__)


# 单个撰写地点用于定位的时间上限，避免一个查不到的地点拖住其余条目。
_AUTHORED_ENTRY_BUDGET_SECONDS = 20.0


_AUTHORED_PLACE_TOOL_NAMES = frozenset({"maps_text_search", "maps_search_detail"})


class _AuthoredEntryBudgetSpent(RuntimeError):
    """单个地点的定位预算已经用完。"""


def _authored_place_tool_access(state: TravelAgentState) -> AuthoredPlaceToolAccess:
    """把地点定位绑定到本次运行受审计的工具入口。"""
    tool_context = build_tool_context_from_state(state)

    async def execute(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return await execute_tool(
            tool_name,
            arguments,
            allowed_tool_names=_AUTHORED_PLACE_TOOL_NAMES,
            node_name=NODE_ITINERARY,
            activation_source="authored_place_resolution",
            allow_fallback=False,
            **tool_context,
        )

    def has_tool(tool_name: str) -> bool:
        # 工具已注册不等于已授权；execute_tool 负责权限校验。
        return get_tool_registry().has_tool(tool_name)

    return AuthoredPlaceToolAccess(execute=execute, has_tool=has_tool)


async def _locate_authored_places(
    composition: ItineraryCompositionDraft,
    scopes: Dict[str, AuthoredPlaceScope],
    tools: AuthoredPlaceToolAccess,
) -> ItineraryCompositionDraft:
    """补齐能定位到的撰写地点；定位不到的条目保留内容，不写坐标。"""
    pending = [ref for ref in authored_places(composition) if not ref.place.is_located]
    if not pending:
        return composition
    located: Dict[str, AuthoredPlaceBase] = {}
    attempted: set[str] = set()
    for index, ref in enumerate(pending):
        place = ref.place
        key = authored_place_key(place)
        if key in located or key in attempted:
            continue
        # 同一地点在同一份草稿里只检索一次；查不到时保留内容、不写坐标。
        attempted.add(key)
        try:
            # 单个未知地点不占用其他条目的定位时间。
            async def _resolve_within_budget(
                place: AuthoredPlaceBase = place,
                kind: str = ref.kind,
                scope: AuthoredPlaceScope = scopes.get(
                    ref.destination_id, AuthoredPlaceScope()
                ),
            ) -> Optional[Dict[str, Any]]:
                try:
                    return await asyncio.wait_for(
                        resolve_authored_place(
                            name=place.name,
                            local_name=place.local_name,
                            city=place.city,
                            address=place.address,
                            kind=kind,
                            scope=scope,
                            tools=tools,
                        ),
                        timeout=_AUTHORED_ENTRY_BUDGET_SECONDS,
                    )
                except asyncio.TimeoutError as spent:
                    raise _AuthoredEntryBudgetSpent(place.name) from spent

            resolved = await await_model_operation(
                _resolve_within_budget(),
                operation="place.resolve_authored",
            )
        except _AuthoredEntryBudgetSpent:
            logger.warning(
                "authored place resolution budget spent name=%s; keeping entry without coordinates",
                place.name,
            )
            continue
        except ModelWindowClosed as closed:
            # 用完的是整个运行窗口，未处理的地点都按无坐标保留。
            logger.warning(
                "%s window closed at elapsed=%.1fs with %s authored entries unresolved",
                closed.window,
                closed.observation.elapsed_seconds,
                len(pending) - index,
            )
            break
        if resolved is None:
            logger.info(
                "authored place not found name=%s; keeping entry without coordinates",
                place.name,
            )
            continue
        located[key] = place.model_copy(
            update={
                "resolved_place_id": resolved["place_id"],
                "resolved_address": resolved["address"],
                "resolved_latitude": resolved["latitude"],
                "resolved_longitude": resolved["longitude"],
            }
        )
    if located:
        composition = map_authored_places(
            composition,
            lambda place: _reuse_place_location(
                place,
                located.get(authored_place_key(place)),
            ),
        )
    return composition


def _reuse_place_location(place, located):
    if located is None:
        return place
    return place.model_copy(
        update={field: getattr(located, field) for field in _SERVER_OWNED_PLACE_FIELDS}
    )


async def locate_authored_composition(
    composition: ItineraryCompositionDraft,
    state: TravelAgentState,
) -> ItineraryCompositionDraft:
    """补齐撰写地点的地图身份，找不到的条目保留内容并按无坐标处理。"""
    scopes = authored_place_scopes(state.controlled_trip_identity)
    tools = _authored_place_tool_access(state)
    return await _locate_authored_places(composition, scopes, tools)


def _reuse_located_places(
    draft: ItineraryCompositionDraft,
    previous: Optional[ItineraryCompositionDraft],
) -> ItineraryCompositionDraft:
    """沿用上一份草稿已定位的地点身份，避免重复检索。"""
    if previous is None:
        return draft
    located = {
        (
            ref.destination_id,
            ref.kind,
            ref.place.name,
            ref.place.local_name,
            ref.place.address,
            ref.place.city,
        ): ref.place
        for ref in authored_places(previous)
        if ref.place.is_located
    }
    days = []
    for day in draft.days:
        placements = []
        for placement in day.placements:
            if (
                placement.placement_kind in {"visit", "dining"}
                and placement.authored_place
            ):
                place = placement.authored_place
                key = (
                    day.destination_id,
                    placement.placement_kind,
                    place.name,
                    place.local_name,
                    place.address,
                    place.city,
                )
                original = located.get(key)
                if original is not None:
                    placement = placement.model_copy(
                        update={
                            "authored_place": _reuse_place_location(place, original),
                        }
                    )
            placements.append(placement)
        days.append(day.model_copy(update={"placements": placements}))
    return draft.model_copy(update={"days": days})
