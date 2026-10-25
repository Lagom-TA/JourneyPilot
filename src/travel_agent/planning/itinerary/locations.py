from __future__ import annotations

import asyncio
import json
import logging
import unicodedata
from typing import Any, Dict, List, Optional

from travel_agent.entities.state import TravelAgentState
from travel_agent.planning.itinerary.draft import (
    _SERVER_OWNED_PLACE_FIELDS,
    AuthoredPlaceBase,
    ItineraryCompositionDraft,
    ItineraryCompositionError,
    authored_place_key,
    authored_places,
    map_authored_places,
)
from travel_agent.planning.nodes import NODE_ITINERARY
from travel_agent.planning.tool_context import build_tool_context_from_state
from travel_agent.runtime.deadlines import observe_run_deadline
from travel_agent.runtime.operations import ModelWindowClosed, await_model_operation
from travel_agent.services.authored_place_resolution import (
    AuthoredPlaceScope,
    AuthoredPlaceToolAccess,
    authored_place_scopes,
    resolve_authored_place,
)
from travel_agent.tools.execution import execute_tool
from travel_agent.tools.registry import get_tool_registry

logger = logging.getLogger(__name__)


_AUTHORED_PLACE_REPLACEMENT_ROUNDS = 1


_AUTHORED_ENTRY_BUDGET_SECONDS = 20.0


_AUTHORED_PLACE_TOOL_NAMES = frozenset({"maps_text_search", "maps_search_detail"})


class _AuthoredEntryBudgetSpent(RuntimeError):
    """One entry's resolution ladder ran its full slice and found nothing."""


_NAME_SEPARATORS = str.maketrans({ch: "" for ch in " \t　・·‧•‐-–—_/"})


def _name_key(value: str) -> str:
    """Match key for one authored name, tolerant of how it was typed."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return text.translate(_NAME_SEPARATORS).casefold()


def _names_disproved(name: str, local_name: str, disproved: set[str]) -> bool:
    """Whether either name of an entry is one this run already disproved."""
    if not disproved:
        return False
    keys = {
        _name_key(value) for value in (name, local_name) if str(value or "").strip()
    }
    return bool(keys & {_name_key(value) for value in disproved})


def _place_names(place: AuthoredPlaceBase) -> set[str]:
    return {
        str(value)
        for value in (place.name, place.local_name)
        if str(value or "").strip()
    }


def _composition_window_closed(state: TravelAgentState) -> bool:
    if state.run_deadline is None:
        return False
    _observed, observation = observe_run_deadline(state.run_deadline)
    return observation.composition_closed


def _authored_place_tool_access(state: TravelAgentState) -> AuthoredPlaceToolAccess:
    """Bind the authored-place ladder to this run's audited tool gateway."""
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
        # Registration does not grant access; execute_tool enforces authorization.
        return get_tool_registry().has_tool(tool_name)

    return AuthoredPlaceToolAccess(execute=execute, has_tool=has_tool)


async def _locate_authored_places(
    composition: ItineraryCompositionDraft,
    scopes: Dict[str, AuthoredPlaceScope],
    unlocatable: set[str],
    tools: AuthoredPlaceToolAccess,
) -> tuple[ItineraryCompositionDraft, list[AuthoredPlaceBase]]:
    """Fill the resolved identity of every authored place a provider knows."""
    pending = [ref for ref in authored_places(composition) if not ref.place.is_located]
    if not pending:
        return composition, []
    located: Dict[str, AuthoredPlaceBase] = {}
    unresolved: List[AuthoredPlaceBase] = []
    for index, ref in enumerate(pending):
        place = ref.place
        key = authored_place_key(place)
        if key in located:
            continue
        if _names_disproved(place.name, place.local_name, unlocatable):
            logger.info("authored place already disproved this run name=%s", place.name)
            unresolved.append(place)
            continue
        try:
            # One unknown place must not consume the other entries' resolution window.
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
            # The ladder had its full slice and produced nothing; a place every
            # provider knows answers in a few seconds.
            logger.warning("authored place resolution budget spent name=%s", place.name)
            unlocatable |= _place_names(place)
            unresolved.append(place)
            continue
        except ModelWindowClosed as closed:
            # The window, not this entry, is what ran out; the rest go unresolved
            # so the itinerary still ships the entries that did resolve.
            logger.warning(
                "%s window closed at elapsed=%.1fs with %s authored entries unresolved",
                closed.window,
                closed.observation.elapsed_seconds,
                len(pending) - index,
            )
            unresolved.extend(item.place for item in pending[index:])
            break
        if resolved is None:
            unlocatable |= _place_names(place)
            unresolved.append(place)
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
    return composition, unresolved


def _replacement_place_schema(original_names: List[str]) -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "replacements": {
                "type": "array",
                "minItems": len(original_names),
                "maxItems": len(original_names),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "original_name": {"type": "string", "enum": original_names},
                        "name": {"type": "string", "minLength": 1},
                        "local_name": {"type": "string", "minLength": 1},
                        "address": {"type": "string", "minLength": 1},
                        "city": {"type": "string", "minLength": 1},
                        "selection_reason": {"type": "string", "minLength": 1},
                    },
                    "required": [
                        "original_name",
                        "name",
                        "local_name",
                        "address",
                        "city",
                        "selection_reason",
                    ],
                },
            }
        },
        "required": ["replacements"],
    }


async def _request_replacement_places(
    llm: Any,
    unresolved: List[AuthoredPlaceBase],
    unlocatable: set[str],
) -> Dict[str, Dict[str, str]]:
    """Ask for one different named place per entry the map could not find."""
    originals = [
        {
            "name": place.name,
            "local_name": place.local_name,
            "city": place.city,
            "address": place.address,
        }
        for place in unresolved
    ]
    original_names = [place.name for place in unresolved]
    # Names an earlier composition attempt already disproved. Naming them keeps
    # the round from spending itself rediscovering the same dead entries.
    pending_keys = {
        _name_key(value) for place in unresolved for value in _place_names(place)
    }
    already_disproved = sorted(
        value for value in unlocatable if _name_key(value) not in pending_keys
    )
    exclusion = (
        f"\n本次运行已确认检索不到、禁止再次使用的名称："
        f"{json.dumps(already_disproved, ensure_ascii=False)}"
        if already_disproved
        else ""
    )
    response = await llm.ainvoke(
        [
            {
                "role": "system",
                "content": (
                    "你是 JourneyPilot 的行程组合器。下列地点在地点库中检索不到，"
                    "为每一个换一个同城、同类型、真实存在且能在地图上检索到的地点。"
                    "换的必须是另一个地点：改写法、换假名拼法、换繁简字形、加减分店后缀"
                    "都算同一个地点，一律不接受。"
                    "只返回替换项：local_name 逐字写当地语言的招牌原名（地点库按它收录，"
                    "字形与当地实际书写一致：中国大陆写简体，日本按招牌上的假名写法），"
                    "name 写旅行者读的常用名称，address 写街道级地址，city 保持同城，"
                    "selection_reason 一句话说明适配理由。不要解释，不要返回完整行程。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"检索不到的地点：{json.dumps(originals, ensure_ascii=False)}"
                    f"{exclusion}"
                ),
            },
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "authored_place_replacements",
                "strict": True,
                "schema": _replacement_place_schema(original_names),
            },
        },
        temperature=0,
    )
    content = response.content if hasattr(response, "content") else response
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    payload = json.loads(content)
    items = payload.get("replacements") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ValueError("place replacement must return one replacements list")
    by_original: Dict[str, Dict[str, str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        original = str(item.get("original_name") or "")
        name = str(item.get("name") or "")
        if not original or not name:
            continue
        local_name = str(item.get("local_name") or name)
        if _names_disproved(name, local_name, unlocatable):
            logger.info(
                "discarding replacement that renames a disproved place name=%s",
                name,
            )
            continue
        by_original[original] = {
            "name": name,
            "local_name": local_name,
            "address": str(item.get("address") or ""),
            "city": str(item.get("city") or ""),
            "selection_reason": str(item.get("selection_reason") or ""),
        }
    return by_original


class AuthoredPlaceLocationError(ItineraryCompositionError):
    def __init__(self, message: str, composition: ItineraryCompositionDraft):
        super().__init__(message)
        self.composition = composition


def _reuse_place_location(place, located):
    if located is None:
        return place
    return place.model_copy(
        update={field: getattr(located, field) for field in _SERVER_OWNED_PLACE_FIELDS}
    )


async def locate_authored_composition(
    composition: ItineraryCompositionDraft,
    llm: Any,
    state: TravelAgentState,
    unlocatable: set[str],
) -> ItineraryCompositionDraft:
    """Return a composition whose every authored entry has a map location."""
    scopes = authored_place_scopes(state.controlled_trip_identity)
    tools = _authored_place_tool_access(state)
    composition, unresolved = await _locate_authored_places(
        composition, scopes, unlocatable, tools
    )
    for _round in range(_AUTHORED_PLACE_REPLACEMENT_ROUNDS):
        if not unresolved:
            break
        if _composition_window_closed(state):
            # Past the boundary a replacement round would spend the model call
            # that composition repair still needs.
            break
        replacements = await _request_replacement_places(llm, unresolved, unlocatable)
        by_key = {
            authored_place_key(place): replacements[place.name]
            for place in unresolved
            if place.name in replacements
        }
        if not by_key:
            break
        composition = map_authored_places(
            composition,
            lambda place: (
                place.model_copy(update=by_key[authored_place_key(place)])
                if authored_place_key(place) in by_key
                else place
            ),
        )
        composition, unresolved = await _locate_authored_places(
            composition, scopes, unlocatable, tools
        )
    if unresolved:
        raise AuthoredPlaceLocationError(
            "authored places could not be located; revise these entries without deleting other content: "
            + "; ".join(
                f"{place.name} ({place.local_name}, {place.city}, {place.address})"
                for place in unresolved
            ),
            composition,
        )
    return composition


def _reuse_located_places(
    draft: ItineraryCompositionDraft,
    previous: Optional[ItineraryCompositionDraft],
) -> ItineraryCompositionDraft:
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
