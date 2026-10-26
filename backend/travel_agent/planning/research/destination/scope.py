"""Planning research destination scope."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from travel_agent.integrations.places.taxonomy import (
    provider_place_type_matches_candidate_kind,
)
from travel_agent.planning.requirements.product_policy import (
    style_selected_physical_candidate_kinds,
)
from travel_agent.planning.research.destination.prompts import (
    DINING_OPTIONS_TEMPLATE,
    KNOWLEDGE_BASE_NOMINATION,
    NO_DINING_OPTIONS,
    TASK_TEMPLATE,
)

_NODE_NAME = "destination_researcher"


_SCOPED_DISCOVERY_TOOLS = (
    "free_web_search",
    "tavily_search",
    "brave_web_search",
    "firecrawl_search",
)


def build_destination_boundaries(
    controlled_trip_identity: Dict[str, Any] | None,
) -> List[Dict[str, Any]]:
    """Project controlled destinations into the boundary shape workers query with."""
    return [
        {
            "destination_id": str(item.get("place_id") or ""),
            "name": str(item.get("name") or ""),
            "country_code": str(item.get("country_code") or "").casefold(),
            "latitude": item.get("latitude"),
            "longitude": item.get("longitude"),
        }
        for item in (controlled_trip_identity or {}).get("destinations", [])
        if isinstance(item, dict)
    ]


def collect_offered_dining_place_ids(
    authoritative_tool_results: List[Dict[str, Any]],
) -> List[str]:
    """Every restaurant the server put on this round's table."""
    place_ids: List[str] = []
    for envelope in authoritative_tool_results:
        if not isinstance(envelope, dict):
            continue
        payload = envelope.get("sanitized_result")
        results = payload.get("results") if isinstance(payload, dict) else None
        for item in results or []:
            if not isinstance(item, dict):
                continue
            place_id = item.get("place_id")
            provider_type = item.get("provider_place_type")
            if not isinstance(place_id, str) or not place_id:
                continue
            if place_id in place_ids or not isinstance(provider_type, str):
                continue
            if provider_place_type_matches_candidate_kind(provider_type, "dining"):
                place_ids.append(place_id)
    return place_ids


def build_destination_task_prompt(
    *,
    task_desc: str,
    user_query: str,
    rag_context_section: str,
    offered_dining_place_ids: List[str],
    destination_boundaries: List[Dict[str, Any]] | None = None,
) -> str:
    """Keep the destination task focused on provider-backed place records."""
    boundaries = json.dumps(destination_boundaries or [], ensure_ascii=False)
    dining_section = DINING_OPTIONS_TEMPLATE.format(
        place_ids="、".join(offered_dining_place_ids) or NO_DINING_OPTIONS,
    )

    knowledge_base_section = (
        f"{rag_context_section}\n\n{KNOWLEDGE_BASE_NOMINATION}"
        if rag_context_section.strip()
        else rag_context_section
    )
    return (
        TASK_TEMPLATE.format(
            task_desc=task_desc,
            user_query=user_query,
            rag_context_section=knowledge_base_section,
        )
        + f"\n受控目的地边界：{boundaries}。所有地点必须保留 Provider 原始国家码并与对应 destination_id 一致。"
        + f"\n{dining_section}"
    )


def dining_intent_in_request(
    task_desc: str,
    user_query: str,
    controlled_trip_identity: Dict[str, Any],
) -> bool:
    """Did this round's request text or interests ask about food at all?"""
    style = controlled_trip_identity.get("style")
    interests = style.get("secondary_interests") if isinstance(style, dict) else []
    normalized_interests = {
        str(interest).strip().casefold()
        for interest in (interests or [])
        if str(interest).strip()
    }
    if normalized_interests.intersection(
        {"food", "dining", "ramen", "美食", "餐饮", "拉面"}
    ):
        return True
    request_text = f"{task_desc} {user_query}".casefold()
    return any(
        token in request_text
        for token in (
            "restaurant",
            "dining",
            "ramen",
            "美食",
            "餐馆",
            "餐厅",
            "拉面",
            "拉麵",
        )
    )


def resolve_discovery_candidate_kinds(
    assignment_required_kinds: List[str] | None,
    *,
    task_desc: str,
    user_query: str,
    controlled_trip_identity: Dict[str, Any],
) -> List[str] | None:
    """Return the domains the deterministic preflight *tries* to ground."""
    if assignment_required_kinds:
        return list(dict.fromkeys(assignment_required_kinds))
    discovery = style_selected_physical_candidate_kinds(controlled_trip_identity)
    if dining_intent_in_request(task_desc, user_query, controlled_trip_identity):
        discovery = discovery | {"dining"}
    return sorted(discovery) or None
