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
    """让工具调用必须显式声明跨日要求。"""

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


def scope_initial_transport_tools(
    available_tools: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """完整调研轮只保留长途 Provider：placement skeleton 尚未形成，
    市内路线工具一律隐藏，避免对未确定的端点发起市内路线查询。"""
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
) -> List[Dict[str, Any]]:
    """本地/同城行程（无城际腿）时移除 12306/duffel，避免空参数误调。"""
    if has_intercity_leg(controlled_trip_identity) is not False:
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
