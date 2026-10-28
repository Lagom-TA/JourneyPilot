from __future__ import annotations

import asyncio
import logging
import math
from typing import Any, Dict, Mapping, Optional

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
from travel_agent.planning.research.candidates import DiningCandidate, VisitCandidate
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.planning.research.evidence import SourceRecord
from travel_agent.tools.execution import execute_tool
from travel_agent.tools.registry import get_tool_registry

logger = logging.getLogger(__name__)


# 单个撰写地点用于定位的时间上限，避免一个查不到的地点占用其余条目的时间。
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


def _candidate_provider_coordinates(
    candidate: VisitCandidate | DiningCandidate,
    sources: Mapping[str, SourceRecord],
) -> Optional[tuple[float, float]]:
    """返回候选来源中与地点身份匹配的 Provider 坐标。"""

    def find(value: Any) -> Optional[tuple[float, float]]:
        if isinstance(value, dict):
            if str(value.get("place_id") or "") == candidate.place_id:
                latitude = value.get("latitude")
                longitude = value.get("longitude")
                if (
                    not isinstance(latitude, bool)
                    and not isinstance(longitude, bool)
                    and isinstance(latitude, (int, float))
                    and isinstance(longitude, (int, float))
                ):
                    point = float(latitude), float(longitude)
                    if (
                        math.isfinite(point[0])
                        and math.isfinite(point[1])
                        and -90 <= point[0] <= 90
                        and -180 <= point[1] <= 180
                    ):
                        return point
            for nested in value.values():
                matched = find(nested)
                if matched is not None:
                    return matched
        elif isinstance(value, list):
            for nested in value:
                matched = find(nested)
                if matched is not None:
                    return matched
        return None

    for source_id in candidate.source_record_ids:
        source = sources.get(source_id)
        if source is None:
            continue
        matched = find(source.snapshot)
        if matched is not None:
            return matched
    return None


def replace_unlocated_authored_places(
    composition: ItineraryCompositionDraft,
    catalog: Optional[RecommendationCatalog],
) -> ItineraryCompositionDraft:
    """把未定位的撰写落位换成同目的地、同类别且未使用的已定位候选。"""
    if catalog is None:
        return composition
    sources = {
        source.source_record_id: source
        for packet in catalog.research_packets
        for source in packet.source_records
    }
    candidates = sorted(
        (
            candidate
            for candidate in catalog.candidate_index().values()
            if isinstance(candidate, (VisitCandidate, DiningCandidate))
            and _candidate_provider_coordinates(candidate, sources) is not None
        ),
        key=lambda candidate: candidate.candidate_id,
    )
    used_candidate_ids = {
        placement.candidate_id
        for day in composition.days
        for placement in day.placements
        if placement.candidate_id
    } | set(composition.lodging_candidate_ids)
    changed = False
    days = []
    for day in composition.days:
        placements = []
        for placement in day.placements:
            authored = getattr(placement, "authored_place", None)
            if authored is None or authored.is_located:
                placements.append(placement)
                continue
            replacement = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.candidate_id not in used_candidate_ids
                    and candidate.destination_id == day.destination_id
                    and candidate.candidate_kind == placement.placement_kind
                    and (
                        placement.placement_kind != "dining"
                        or placement.meal_type in candidate.meal_types
                    )
                ),
                None,
            )
            if replacement is None:
                placements.append(placement)
                continue
            # 展示理由由候选提供；原撰写条目的名称与理由不转移到新地点。
            placement = placement.model_copy(
                update={
                    "candidate_id": replacement.candidate_id,
                    "authored_place": None,
                    "selection_reason": None,
                }
            )
            used_candidate_ids.add(replacement.candidate_id)
            changed = True
            placements.append(placement)
        days.append(day.model_copy(update={"placements": placements}))
    if not changed:
        return composition
    return composition.model_copy(update={"days": days})


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
