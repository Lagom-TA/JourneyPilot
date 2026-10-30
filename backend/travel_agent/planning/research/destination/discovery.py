from __future__ import annotations

import logging
from typing import Any, Dict, List

from travel_agent.planning.research.destination.dining_binding import (
    _cn_only_destination_boundaries,
    amap_dining_keywords,
    discover_amap_dining,
    select_amap_dining_query,
)
from travel_agent.planning.research.destination.scope import (
    _NODE_NAME,
    _SCOPED_DISCOVERY_TOOLS,
)
from travel_agent.planning.research.domains import ResearchDomain
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
from travel_agent.tools.content import compact_tool_content_for_model
from travel_agent.tools.execution import execute_tool
from travel_agent.tools.governance import (
    PROVIDER_RESULT_OUTCOME_EMPTY_SUCCESS, PROVIDER_RESULT_OUTCOME_METADATA_KEY,
)

logger = logging.getLogger(__name__)


def build_semantic_discovery_arguments(query: ResearchQuery) -> Dict[str, Any]:
    """网页发现工具只接收已批准查询文本。"""
    return {"query": query.query_text, "max_results": 5}


def build_semantic_amap_arguments(
    query: ResearchQuery, boundary: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        "keywords": " ".join(query.aliases)
        or ("景点" if query.domain is ResearchDomain.VISIT else "餐饮"),
        "city": str(boundary.get("name") or ""),
    }


def build_global_place_search_arguments(
    query: ResearchQuery, boundary: Dict[str, Any], candidate_kind: str
) -> Dict[str, Any]:
    destination_id = str(boundary.get("destination_id") or "")
    arguments: Dict[str, Any] = {
        "query": query.query_text,
        "country_code": str(boundary.get("country_code") or "").casefold(),
        "limit": 10,
        "candidate_kind": candidate_kind,
        "aliases": list(query.aliases),
        "destination_place_id": destination_id,
    }
    latitude, longitude = boundary.get("latitude"), boundary.get("longitude")
    if isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)):
        arguments.update(
            destination_latitude=latitude, destination_longitude=longitude
        )
    return arguments


async def discover_and_resolve_required_places(
    *,
    messages: List[Dict[str, Any]],
    available_tools: List[Dict[str, Any]],
    required_candidate_kinds: List[str] | None,
    destination_boundaries: List[Dict[str, Any]],
    tool_context: Dict[str, Any],
    authoritative_tool_results: List[Dict[str, Any]],
    planned_queries: List[ResearchQuery],
    executed_query_ids: List[str],
) -> None:
    """为范围内缺失的地点领域执行确定性发现，并绑定稳定的 Provider 身份。"""
    required_kinds = list(dict.fromkeys(required_candidate_kinds or []))
    if not required_kinds or (
        len(destination_boundaries) == 1
        and has_required_provider_place_selection(
            authoritative_tool_messages(authoritative_tool_results),
            expected_worker=_NODE_NAME,
            required_candidate_kinds=required_kinds,
        )
    ):
        return
    available_names = {
        tool.get("schema", {}).get("function", {}).get("name", "")
        for tool in available_tools
    }
    discovery_name = next(
        (name for name in _SCOPED_DISCOVERY_TOOLS if name in available_names),
        None,
    )
    fallback_policy = FallbackQueryPolicy()
    discovered_domains: set[tuple[str, ResearchDomain]] = set()

    async def discover_semantic_query(query: ResearchQuery) -> bool:
        """发现查询只提名名称，不用于查询地点身份。"""
        name = discovery_name
        arguments: Dict[str, Any] = build_semantic_discovery_arguments(query)
        if (
            name is None
            and _cn_only_destination_boundaries(destination_boundaries)
            and "maps_text_search" in available_names
        ):
            boundary = next(
                (
                    row
                    for row in destination_boundaries
                    if row.get("destination_id") == query.destination_id
                ),
                None,
            )
            if boundary is None:
                return False
            name = "maps_text_search"
            arguments = build_semantic_amap_arguments(query, boundary)
        if name is None:
            return False
        envelope = await execute_tool(
            name,
            arguments,
            available_tools=available_tools,
            node_name=_NODE_NAME,
            activation_source=f"research_query:{query.query_id}",
            **tool_context,
        )
        executed_query_ids.append(query.query_id)
        messages.append(
            {"role": "tool", "content": compact_tool_content_for_model(envelope)}
        )
        authoritative_tool_results.append(envelope)
        metadata = envelope.get("metadata")
        empty = isinstance(metadata, dict) and (
            metadata.get(PROVIDER_RESULT_OUTCOME_METADATA_KEY) == PROVIDER_RESULT_OUTCOME_EMPTY_SUCCESS
        )
        if envelope.get("status") == "success" and not empty:
            discovered_domains.add((query.destination_id, query.domain))
        return True

    def domain_queries(
        domain: ResearchDomain, destination_id: str
    ) -> List[ResearchQuery]:
        scoped = [
            query
            for query in planned_queries
            if query.domain is domain and query.destination_id == destination_id
        ]
        return [
            *[
                query
                for query in scoped
                if query.query_kind
                in {
                    ResearchQueryKind.INTENT_PRIMARY,
                    ResearchQueryKind.STRUCTURAL,
                    ResearchQueryKind.TARGETED_REPAIR,
                }
            ],
            *[
                query
                for query in scoped
                if query.query_kind is ResearchQueryKind.GENERIC_FALLBACK
            ],
        ]

    def allowed(query: ResearchQuery) -> bool:
        if query.query_kind is not ResearchQueryKind.GENERIC_FALLBACK:
            return True
        if (query.destination_id, query.domain) in discovered_domains:
            return False
        research_window_open, run_budget_available = runtime_fallback_capacity()
        return fallback_policy.is_allowed(
            query,
            executed_query_ids=set(executed_query_ids),
            research_window_open=research_window_open,
            run_budget_available=run_budget_available,
        )

    for boundary in destination_boundaries:
        destination_id = str(boundary.get("destination_id") or "")
        country_code = str(boundary.get("country_code") or "").casefold()
        if not destination_id or not country_code:
            continue

        if "visit" in required_kinds:
            for query in domain_queries(ResearchDomain.VISIT, destination_id):
                if not allowed(query):
                    continue
                if query.provider_route != "global_place_search":
                    await discover_semantic_query(query)
                    continue
                if "global_place_search" not in available_names:
                    continue
                arguments = build_global_place_search_arguments(
                    query, boundary, "visit"
                )
                envelope = await execute_tool(
                    "global_place_search", arguments, available_tools=available_tools,
                    node_name=_NODE_NAME, activation_source=f"research_query:{query.query_id}",
                    **tool_context,
                )
                executed_query_ids.append(query.query_id)
                messages.append({"role": "tool", "content": compact_tool_content_for_model(envelope)})
                authoritative_tool_results.append(envelope)
                result = envelope.get("sanitized_result")
                if isinstance(result, dict) and result.get("results"):
                    discovered_domains.add((destination_id, query.domain))
                    break

        if "dining" not in required_kinds:
            continue
        dining_queries = domain_queries(ResearchDomain.DINING, destination_id)
        if not dining_queries:
            continue
        amap_query = select_amap_dining_query(dining_queries)
        if (
            _cn_only_destination_boundaries([boundary])
            and "maps_text_search" in available_names
            and str(boundary.get("name") or "").strip()
        ):
            amap_keywords = amap_dining_keywords(amap_query)
            found = await discover_amap_dining(
                messages=messages,
                available_tools=available_tools,
                destination_boundaries=[boundary],
                tool_context=tool_context,
                authoritative_tool_results=authoritative_tool_results,
                query_text=amap_keywords,
            )
            executed_query_ids.append(amap_query.query_id)
            if found:
                discovered_domains.add((destination_id, ResearchDomain.DINING))
                continue

        if discovery_name is None:
            continue
        for query in dining_queries:
            if not allowed(query):
                continue
            if query.provider_route != "global_place_search":
                await discover_semantic_query(query)
                continue
            if "global_place_search" not in available_names:
                continue
            arguments = build_global_place_search_arguments(
                query, boundary, "dining"
            )
            envelope = await execute_tool(
                "global_place_search", arguments, available_tools=available_tools,
                node_name=_NODE_NAME, activation_source=f"research_query:{query.query_id}",
                **tool_context,
            )
            executed_query_ids.append(query.query_id)
            messages.append({"role": "tool", "content": compact_tool_content_for_model(envelope)})
            authoritative_tool_results.append(envelope)
            result = envelope.get("sanitized_result") or {}
            places = result.get("results") if isinstance(result, dict) else None
            if places:
                logger.info("[destination_researcher] dining identities injected for %s: %d", boundary.get("name", ""), len(places))
                discovered_domains.add((destination_id, query.domain))
                break
