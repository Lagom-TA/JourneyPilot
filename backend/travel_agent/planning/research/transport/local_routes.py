"""Planning research transport local routes."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from travel_agent.planning.research.output.options import (
    has_provider_route_selection_option,
)
from travel_agent.planning.research.output.transcript import authoritative_tool_messages
from travel_agent.planning.research.transport.endpoints import (
    _routable_connector_endpoints,
)
from travel_agent.planning.research.transport.scope import _NODE_NAME
from travel_agent.planning.state import TravelAgentState
from travel_agent.tools.content import compact_tool_content_for_model
from travel_agent.tools.execution import execute_tool
from travel_agent.tools.registry import get_tool_registry

logger = logging.getLogger(__name__)


_LOCAL_ROUTE_TOOL_NAMES = frozenset({"global_route_search"})


_MAX_CONNECTOR_ROUTE_QUERIES_PER_ROUND = 12


async def discover_required_local_route(
    *,
    state: TravelAgentState,
    messages: List[Dict[str, Any]],
    required_transport_classes: List[str] | None,
    connector_gaps: List[Dict[str, Any]] | None,
    tool_context: Dict[str, Any],
    authoritative_tool_results: List[Dict[str, Any]],
) -> bool:
    """Query every exact placement-derived adjacency gap, never an arbitrary pair."""
    required = [
        transport_class
        for transport_class in (required_transport_classes or [])
        if transport_class in {"public_transit", "flexible"}
    ]
    if (
        not required
        or "long_distance" in (required_transport_classes or [])
        or not connector_gaps
    ):
        return False

    if not get_tool_registry().has_tool("global_route_search"):
        logger.warning(
            "[transport_researcher] skip connector gap: "
            "global_route_search is not registered"
        )
        return False

    endpoint_index: Dict[str, Dict[str, Any]] = {}
    for endpoint in _routable_connector_endpoints(state):
        endpoint_index.setdefault(endpoint["place_id"], endpoint)
    routable: List[Dict[str, Any]] = []
    comparisons: List[Dict[str, Any]] = []
    unroutable: List[str] = []
    for gap in connector_gaps:
        from_place_id = str(gap.get("from_place_id") or "").strip()
        to_place_id = str(gap.get("to_place_id") or "").strip()
        origin = endpoint_index.get(from_place_id)
        destination = endpoint_index.get(to_place_id)
        departure_time = str(gap.get("departure_time") or "").strip()
        requested_mode = str(gap.get("requested_mode") or "").strip()
        reason = ""
        if origin is None or destination is None:
            reason = "no located endpoint for " + " and ".join(
                place_id
                for place_id, endpoint in (
                    (from_place_id, origin),
                    (to_place_id, destination),
                )
                if endpoint is None
            )
        elif origin["destination_id"] != destination["destination_id"]:
            reason = "endpoints sit in different controlled destinations"
        elif not departure_time:
            reason = "gap carries no departure time"
        elif requested_mode not in {
            "public_transit",
            "walk",
            "bike",
            "drive",
            "taxi",
            "ride_hailing",
        }:
            reason = f"requested mode {requested_mode!r} is not routable"
        if reason:
            unroutable.append(f"{gap.get('gap_id')}: {reason}")
            continue
        routable.append(
            {
                "from_name": origin["name"],
                "from_place_id": origin["place_id"],
                "from_latitude": origin["latitude"],
                "from_longitude": origin["longitude"],
                "to_name": destination["name"],
                "to_place_id": destination["place_id"],
                "to_latitude": destination["latitude"],
                "to_longitude": destination["longitude"],
                "departure_time": departure_time,
                "mode": requested_mode,
            }
        )
        if gap.get("compare_default_walk") and requested_mode == "public_transit":
            comparisons.append({**routable[-1], "mode": "walk"})
    if unroutable:
        logger.warning(
            "[transport_researcher] %d of %d connector gaps are not routable: %s",
            len(unroutable),
            len(connector_gaps),
            "; ".join(unroutable),
        )
    if not routable:
        return False

    from travel_agent.utils.geography import haversine_km

    comparisons.sort(
        key=lambda request: haversine_km(
            request["from_latitude"],
            request["from_longitude"],
            request["to_latitude"],
            request["to_longitude"],
        )
    )
    queried = (routable + comparisons)[:_MAX_CONNECTOR_ROUTE_QUERIES_PER_ROUND]
    if len(routable) > len(queried):
        logger.warning(
            "[transport_researcher] connector round bounded: querying %d of %d "
            "routable adjacencies; the rest stay authored this round",
            len(queried),
            len(routable),
        )
    for request in queried:
        envelope = await execute_tool(
            "global_route_search",
            request,
            allowed_tool_names=_LOCAL_ROUTE_TOOL_NAMES,
            node_name=_NODE_NAME,
            activation_source="placement_adjacency_connector_gap",
            allow_fallback=False,
            **tool_context,
        )
        messages.append(
            {
                "role": "tool",
                "content": compact_tool_content_for_model(envelope),
            }
        )
        authoritative_tool_results.append(envelope)
    logger.info(
        "[transport_researcher] connector gaps queried %d/%d (routable=%d)",
        len(queried),
        len(connector_gaps),
        len(routable),
    )
    return has_provider_route_selection_option(
        authoritative_tool_messages(authoritative_tool_results),
        required_transport_classes=required_transport_classes,
    )
