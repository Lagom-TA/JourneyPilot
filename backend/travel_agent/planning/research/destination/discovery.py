"""Planning research destination discovery."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from travel_agent.planning.research.destination.dining_binding import (
    _cn_only_destination_boundaries,
    discover_amap_dining,
)
from travel_agent.planning.research.destination.dining_quality import (
    _web_search_entries,
    dining_quality_source_matches_place,
    resolve_dining_locality_tokens,
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
from travel_agent.tools.governance import QUALITY_VERIFIED_PLACE_IDS_METADATA_KEY

logger = logging.getLogger(__name__)


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
    """Deterministically close discovery -> stable Provider identity for scoped gaps."""
    required_kinds = list(dict.fromkeys(required_candidate_kinds or []))
    if not required_kinds or has_required_provider_place_selection(
        authoritative_tool_messages(authoritative_tool_results),
        expected_worker=_NODE_NAME,
        required_candidate_kinds=required_kinds,
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
    country_codes = {
        boundary.get("country_code", "").casefold()
        for boundary in destination_boundaries
        if boundary.get("country_code")
    }
    country_code = next(iter(country_codes)) if len(country_codes) == 1 else None
    fallback_policy = FallbackQueryPolicy()
    discovered_domains: set[ResearchDomain] = set()

    async def discover_semantic_query(query: ResearchQuery) -> bool:
        """Discovery text nominates names; it is never an identity lookup."""
        name = discovery_name
        arguments: Dict[str, Any] = {"query": query.query_text, "max_results": 5}
        if (
            name is None
            and _cn_only_destination_boundaries(destination_boundaries)
            and "maps_text_search" in available_names
        ):
            name = "maps_text_search"
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

            arguments = {
                "keywords": " ".join(query.aliases)
                or ("景点" if query.domain is ResearchDomain.VISIT else "餐饮"),
                "city": str(boundary.get("name") or ""),
            }
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
        if envelope.get("status") == "success" and _web_search_entries(
            envelope.get("sanitized_result")
        ):
            discovered_domains.add(query.domain)
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

    if "visit" in required_kinds and country_code and len(destination_boundaries) == 1:
        boundary = destination_boundaries[0]
        destination_id = boundary.get("destination_id")
        for query in domain_queries(ResearchDomain.VISIT, str(destination_id or "")):
            if query.query_kind is ResearchQueryKind.GENERIC_FALLBACK:
                if query.domain in discovered_domains:
                    continue
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
            if query.provider_route != "global_place_search":
                await discover_semantic_query(query)
                continue
            if "global_place_search" not in available_names:
                continue
            visit_arguments: Dict[str, Any] = {
                "query": query.query_text,
                "country_code": country_code,
                "limit": 10,
                "candidate_kind": "visit",
                "aliases": query.aliases,
            }
            if destination_id:
                visit_arguments["destination_place_id"] = destination_id
            latitude = boundary.get("latitude")
            longitude = boundary.get("longitude")
            if isinstance(latitude, (int, float)) and isinstance(
                longitude, (int, float)
            ):
                visit_arguments["destination_latitude"] = latitude
                visit_arguments["destination_longitude"] = longitude
            visit_envelope = await execute_tool(
                "global_place_search",
                visit_arguments,
                available_tools=available_tools,
                node_name=_NODE_NAME,
                activation_source=f"research_query:{query.query_id}",
                **tool_context,
            )
            executed_query_ids.append(query.query_id)
            messages.append(
                {
                    "role": "tool",
                    "content": compact_tool_content_for_model(visit_envelope),
                }
            )
            authoritative_tool_results.append(visit_envelope)
            visit_result = visit_envelope.get("sanitized_result")
            visit_places = (
                visit_result.get("results") if isinstance(visit_result, dict) else None
            ) or []
            if visit_places:
                break

    if "dining" not in required_kinds:
        return

    dining_queries = domain_queries(
        ResearchDomain.DINING,
        str(destination_boundaries[0].get("destination_id") or "")
        if len(destination_boundaries) == 1
        else "",
    )
    if dining_queries:
        amap_query = dining_queries[0]
        amap_attempted = (
            _cn_only_destination_boundaries(destination_boundaries)
            and "maps_text_search" in available_names
        )
        if amap_attempted:
            executed_query_ids.append(amap_query.query_id)
        if await discover_amap_dining(
            messages=messages,
            available_tools=available_tools,
            destination_boundaries=destination_boundaries,
            tool_context=tool_context,
            authoritative_tool_results=authoritative_tool_results,
            query_text=" ".join(amap_query.aliases) or "餐饮",
        ):
            return

    if discovery_name is None:
        return

    if country_code and len(destination_boundaries) == 1:
        boundary = destination_boundaries[0]
        destination_id = boundary.get("destination_id")
        selected: List[Dict[str, Any]] = []
        identity_envelope: Dict[str, Any] = {}
        for query in domain_queries(ResearchDomain.DINING, str(destination_id or "")):
            if query.query_kind is ResearchQueryKind.GENERIC_FALLBACK:
                if query.domain in discovered_domains:
                    continue
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
            if query.provider_route != "global_place_search":
                await discover_semantic_query(query)
                continue
            if "global_place_search" not in available_names:
                continue
            identity_arguments: Dict[str, Any] = {
                "query": query.query_text,
                "country_code": country_code,
                "limit": 10,
                "candidate_kind": "dining",
                "aliases": query.aliases,
            }
            if destination_id:
                identity_arguments["destination_place_id"] = destination_id
            latitude = boundary.get("latitude")
            longitude = boundary.get("longitude")
            if isinstance(latitude, (int, float)) and isinstance(
                longitude, (int, float)
            ):
                identity_arguments["destination_latitude"] = latitude
                identity_arguments["destination_longitude"] = longitude
            identity_envelope = await execute_tool(
                "global_place_search",
                identity_arguments,
                available_tools=available_tools,
                node_name=_NODE_NAME,
                activation_source=f"research_query:{query.query_id}",
                **tool_context,
            )
            executed_query_ids.append(query.query_id)
            identity_payload = identity_envelope.get("sanitized_result") or {}
            identity_results = (
                identity_payload.get("results")
                if isinstance(identity_payload, dict)
                else None
            )
            selected = [
                item
                for item in (identity_results or [])[:3]
                if isinstance(item, dict) and item.get("name") and item.get("place_id")
            ]
            if selected:
                break

        locality_tokens_by_place = await resolve_dining_locality_tokens(selected)
        verified_quality_envelopes: List[Dict[str, Any]] = []
        for item in selected:
            place_id = str(item["place_id"])
            locality_tokens = locality_tokens_by_place.get(place_id) or []
            if not locality_tokens:
                logger.info(
                    "[destination_researcher] dining quality unverifiable for %s (%s): no locality token",
                    item.get("name"),
                    place_id,
                )
                continue
            aliases = (
                item.get("aliases") if isinstance(item.get("aliases"), list) else []
            )
            quality_name = next(
                (
                    alias
                    for alias in aliases
                    if isinstance(alias, str) and re.search(r"[A-Za-z]", alias)
                ),
                str(item["name"]),
            )
            quality_envelope = await execute_tool(
                discovery_name,
                {
                    "query": f'"{quality_name}" {" ".join(locality_tokens[:2])} reviews',
                    "max_results": 10,
                },
                available_tools=available_tools,
                node_name=_NODE_NAME,
                activation_source="candidate_gate_deterministic_quality",
                **tool_context,
            )
            if quality_envelope.get(
                "status"
            ) == "success" and dining_quality_source_matches_place(
                item,
                quality_envelope.get("sanitized_result") or {},
                locality_tokens=locality_tokens,
            ):
                bound_quality = dict(quality_envelope)
                quality_metadata = dict(bound_quality.get("metadata") or {})
                quality_metadata[QUALITY_VERIFIED_PLACE_IDS_METADATA_KEY] = [place_id]
                bound_quality["metadata"] = quality_metadata
                verified_quality_envelopes.append(bound_quality)
        if selected:
            logger.info(
                "[destination_researcher] dining options injected for %s: "
                "%d identities, %d quality-verified",
                boundary.get("name", ""),
                len(selected),
                len(verified_quality_envelopes),
            )
            for envelope in verified_quality_envelopes:
                messages.append(
                    {
                        "role": "tool",
                        "content": compact_tool_content_for_model(envelope),
                    }
                )
                authoritative_tool_results.append(envelope)
            messages.append(
                {
                    "role": "tool",
                    "content": compact_tool_content_for_model(identity_envelope),
                }
            )
            authoritative_tool_results.append(identity_envelope)
