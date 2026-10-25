"""Planning research transport scope."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from travel_agent.planning.research.provider_assignments import (
    parse_provider_evidence_assignments,
)
from travel_agent.planning.state import TravelAgentState


_NODE_NAME = "transport_researcher"


def constrain_cross_day_flight_tools(
    available_tools: List[Dict[str, Any]],
    *,
    required: bool,
) -> List[Dict[str, Any]]:
    """Make the explicit cross-day requirement unavoidable in tool calls."""

    if not required:
        return available_tools
    constrained: List[Dict[str, Any]] = []
    for tool in available_tools:
        if (
            tool.get("server_name") != "duffel-flights"
            or tool.get("schema", {}).get("function", {}).get("name")
            != "search_flights"
        ):
            constrained.append(tool)
            continue
        copied = deepcopy(tool)
        parameters = copied["schema"]["function"].setdefault(
            "parameters", {"type": "object"}
        )
        params_schema = parameters.setdefault("properties", {}).setdefault(
            "params", {"type": "object"}
        )
        params_schema.setdefault("properties", {})["require_cross_day"] = {
            "type": "boolean",
            "const": True,
            "description": "用户明确要求真实跨日或跨夜长途路线",
        }
        required_fields = params_schema.setdefault("required", [])
        if "require_cross_day" not in required_fields:
            required_fields.append("require_cross_day")
        constrained.append(copied)
    return constrained


def scope_transport_gap_tools(
    available_tools: List[Dict[str, Any]],
    recommended_tools: List[str],
    required_transport_classes: List[str] | None,
    *,
    scoped_retry: bool = False,
) -> List[Dict[str, Any]]:
    """Expose the small recommended tool set directly for any scoped retry."""
    if not (required_transport_classes or scoped_retry) or not recommended_tools:
        return available_tools
    recommended_set = set(recommended_tools)

    long_distance_scope = "long_distance" in (required_transport_classes or ())
    if not long_distance_scope:
        global_provider = [
            tool
            for tool in available_tools
            if tool.get("schema", {}).get("function", {}).get("name", "")
            == "global_route_search"
            and "global_route_search" in recommended_set
        ]
        if global_provider:
            return global_provider
    scoped = [
        tool
        for tool in available_tools
        if tool.get("schema", {}).get("function", {}).get("name", "") in recommended_set
    ]
    return scoped or available_tools


def scope_initial_transport_tools(
    available_tools: List[Dict[str, Any]],
    *,
    require_current_candidate: bool,
    connector_gaps: List[Dict[str, Any]] | None,
) -> List[Dict[str, Any]]:
    """Hide local-route providers until an exact placement gap exists."""
    if require_current_candidate or connector_gaps:
        return available_tools
    return [
        tool
        for tool in available_tools
        if (
            tool.get("schema", {}).get("function", {}).get("name", "")
            != "global_route_search"
            and tool.get("server_name") != "amap-maps"
        )
    ]


_LONG_DISTANCE_TRANSPORT_SERVERS = frozenset({"12306-train", "duffel-flights"})


def has_intercity_leg(
    controlled_trip_identity: Dict[str, Any] | None,
) -> Optional[bool]:
    """行程是否含城际腿。"""
    identity = controlled_trip_identity or {}
    destinations = identity.get("destinations") or []
    if not destinations:
        return None
    places: List[Dict[str, Any]] = []
    origin = identity.get("origin") or {}
    if origin:
        places.append(origin)
    places.extend(dest for dest in destinations if dest)
    place_ids = {
        str(place.get("place_id") or "").strip()
        for place in places
        if str(place.get("place_id") or "").strip()
    }
    if len(place_ids) >= 2:
        return True
    names = {
        str(place.get("name") or "").strip()
        for place in places
        if str(place.get("name") or "").strip()
    }
    if len(names) >= 2:
        return True
    return False


def scope_long_distance_transport_tools(
    available_tools: List[Dict[str, Any]],
    *,
    controlled_trip_identity: Dict[str, Any] | None,
    connector_gaps: List[Dict[str, Any]] | None,
) -> List[Dict[str, Any]]:
    """本地/同城行程（无城际腿）时移除 12306/duffel，避免空参数误调。"""
    if connector_gaps or has_intercity_leg(controlled_trip_identity) is not False:
        return available_tools
    return [
        tool
        for tool in available_tools
        if tool.get("server_name") not in _LONG_DISTANCE_TRANSPORT_SERVERS
    ]


def transport_provider_assignments(assignment: Dict[str, Any], state: TravelAgentState):
    return parse_provider_evidence_assignments(
        assignment,
        expected_worker=_NODE_NAME,
        expected_run_id=state.run_id,
        expected_constraint_pack_revision=state.constraint_pack_revision,
    )
