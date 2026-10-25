"""Planning research destination operating information."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from travel_agent.integrations.places.taxonomy import (
    provider_place_type_matches_candidate_kind,
)
from travel_agent.planning.research.destination.scope import (
    _NODE_NAME,
    _SCOPED_DISCOVERY_TOOLS,
)
from travel_agent.planning.research.output.policy import packet_candidate_limit
from travel_agent.runtime.cancellation import RunCancelled
from travel_agent.tools.content import compact_tool_content_for_model
from travel_agent.tools.execution import execute_tool

logger = logging.getLogger(__name__)


async def collect_place_operating_information(
    *,
    available_tools: List[Dict[str, Any]],
    tool_context: Dict[str, Any],
    authoritative_tool_results: List[Dict[str, Any]],
    messages: List[Dict[str, Any]],
) -> None:
    """Look up venue operations after names are resolved, with real tools only."""
    names = {
        tool.get("schema", {}).get("function", {}).get("name")
        for tool in available_tools
    }
    search_name = next(
        (name for name in _SCOPED_DISCOVERY_TOOLS if name in names), None
    )
    if search_name is None:
        return
    places: dict[str, Dict[str, Any]] = {}
    for envelope in authoritative_tool_results:
        if (
            envelope.get("tool_name") != "global_place_search"
            or envelope.get("status") != "success"
        ):
            continue
        result = envelope.get("sanitized_result")
        for place in result.get("results", []) if isinstance(result, dict) else []:
            if (
                isinstance(place, dict)
                and place.get("place_id")
                and place.get("name")
                and provider_place_type_matches_candidate_kind(
                    str(place.get("provider_place_type") or ""), "visit"
                )
            ):
                places.setdefault(str(place["place_id"]), place)
    for place in list(places.values())[: packet_candidate_limit(_NODE_NAME)]:
        country = str(place.get("provider_country_code") or "").casefold()
        terms = (
            "官网 开放时间 最后入场 预约 闭馆"
            if country == "cn"
            else "official opening hours last admission reservation closure"
        )
        try:
            envelope = await execute_tool(
                search_name,
                {"query": f'"{place["name"]}" {terms}', "max_results": 3},
                available_tools=available_tools,
                node_name=_NODE_NAME,
                activation_source="place_operating_information",
                **tool_context,
            )
        except RunCancelled:
            raise
        except Exception:
            logger.warning(
                "Operating information unavailable for %s; retain unknown",
                place["name"],
                exc_info=True,
            )
            break
        authoritative_tool_results.append(envelope)
        messages.append(
            {"role": "tool", "content": compact_tool_content_for_model(envelope)}
        )
