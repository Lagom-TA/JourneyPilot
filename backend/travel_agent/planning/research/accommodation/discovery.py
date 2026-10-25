"""Planning research accommodation discovery."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping

from travel_agent.planning.research.accommodation.binding import (
    _bind_amap_lodging,
    _bind_nominatim_lodging,
)
from travel_agent.planning.research.accommodation.scope import _NODE_NAME
from travel_agent.planning.research.fallback_policy import (
    FallbackQueryPolicy,
    runtime_fallback_capacity,
)
from travel_agent.planning.research.output.options import (
    has_required_provider_place_selection,
)
from travel_agent.planning.research.output.transcript import authoritative_tool_messages
from travel_agent.planning.research.query_contracts import (
    ResearchQuery,
    ResearchQueryKind,
)
from travel_agent.planning.state import TravelAgentState

logger = logging.getLogger(__name__)


async def discover_deterministic_hotels(
    *,
    state: TravelAgentState,
    messages: List[Dict[str, Any]],
    available_tools: List[Dict[str, Any]],
    tool_context: Dict[str, Any],
    authoritative_tool_results: List[Dict[str, Any]],
    planned_queries: List[ResearchQuery],
    executed_query_ids: List[str],
) -> bool:
    """Ground lodging identity for every controlled destination from real Provider data."""
    identity = state.controlled_trip_identity or {}
    if not isinstance(identity, Mapping):
        logger.info(
            "[accommodation_researcher] deterministic lodging skip: identity not a mapping (%s)",
            type(identity).__name__,
        )
        return False
    destinations = identity.get("destinations")
    if not isinstance(destinations, list) or not destinations:
        logger.info(
            "[accommodation_researcher] deterministic lodging skip: no destinations"
        )
        return False
    available_names = {
        tool.get("schema", {}).get("function", {}).get("name", "")
        for tool in available_tools
    }
    bound: List[str] = []
    unbound: List[str] = []
    fallback_policy = FallbackQueryPolicy()
    for dest in destinations:
        if not isinstance(dest, Mapping):
            continue
        dest_name = str(dest.get("name") or "").strip()
        if not dest_name:
            continue
        destination_queries = [
            query
            for query in planned_queries
            if query.destination_id == str(dest.get("place_id") or "")
        ]
        primary_queries = [
            query
            for query in destination_queries
            if query.query_kind
            in {
                ResearchQueryKind.INTENT_PRIMARY,
                ResearchQueryKind.STRUCTURAL,
                ResearchQueryKind.TARGETED_REPAIR,
            }
        ]
        fallback_queries = [
            query
            for query in destination_queries
            if query.query_kind is ResearchQueryKind.GENERIC_FALLBACK
        ]
        injected = False
        # These provider paths are mutually exclusive, not fallbacks for each other.
        provider = (
            "amap"
            if str(dest.get("country_code") or "").lower() == "cn"
            else "nominatim"
        )
        for query in [*primary_queries, *fallback_queries]:
            if query.query_kind is ResearchQueryKind.GENERIC_FALLBACK:
                research_window_open, run_budget_available = runtime_fallback_capacity()
                if not fallback_policy.is_allowed(
                    query,
                    executed_query_ids=set(executed_query_ids),
                    admitted_candidate_count=0,
                    required_candidate_count=1,
                    research_window_open=research_window_open,
                    run_budget_available=run_budget_available,
                ):
                    continue
            if provider == "amap" and "maps_text_search" in available_names:
                executed_query_ids.append(query.query_id)
                injected = await _bind_amap_lodging(
                    dest,
                    messages=messages,
                    available_tools=available_tools,
                    tool_context=tool_context,
                    authoritative_tool_results=authoritative_tool_results,
                    query_text=query.query_text,
                )
            elif provider == "nominatim" and "global_place_search" in available_names:
                executed_query_ids.append(query.query_id)
                injected = await _bind_nominatim_lodging(
                    dest,
                    messages=messages,
                    available_tools=available_tools,
                    tool_context=tool_context,
                    authoritative_tool_results=authoritative_tool_results,
                    query_text=query.query_text,
                )
            if injected:
                break
        (bound if injected else unbound).append(f"{dest_name}/{provider}")
    logger.info(
        "[accommodation_researcher] deterministic lodging binding: bound=%s unbound=%s",
        bound or "-",
        unbound or "-",
    )
    if not bound:
        return False
    return has_required_provider_place_selection(
        authoritative_tool_messages(authoritative_tool_results),
        expected_worker=_NODE_NAME,
        required_candidate_kinds=["lodging"],
    )
