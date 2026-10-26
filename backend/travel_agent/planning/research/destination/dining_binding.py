"""Planning research destination dining binding."""

from __future__ import annotations

import datetime
import json
import logging
from typing import Any, Dict, List

from travel_agent.planning.requirements.destination_scope import (
    annotate_destination_distance,
)
from travel_agent.planning.research.destination.dining_parsing import (
    _extract_amap_tool_text,
    _parse_amap_restaurants,
    _restaurants_from_pois,
)
from travel_agent.planning.research.destination.scope import _NODE_NAME
from travel_agent.planning.research.output.options import (
    has_required_provider_place_selection,
)
from travel_agent.planning.research.output.transcript import authoritative_tool_messages
from travel_agent.tools.content import compact_tool_content_for_model
from travel_agent.tools.execution import execute_tool
from travel_agent.utils.coordinates import amap_location_to_wgs84

logger = logging.getLogger(__name__)


def _build_amap_dining_identity_envelope(
    *,
    results: List[Dict[str, Any]],
    audit_id: str,
    retrieved_at: str,
) -> Dict[str, Any]:
    return {
        "tool_name": "global_place_search",
        "server_name": "amap-maps",
        "status": "success",
        "audit_id": audit_id,
        "retrieved_at": retrieved_at,
        "metadata": {"evidence_allowed": True},
        "sanitized_result": {
            "success": True,
            "provider": "amap",
            "results": results,
        },
    }


async def _enrich_amap_dining_coordinates(
    restaurants: List[Dict[str, Any]],
    *,
    available_tools: List[Dict[str, Any]],
    tool_context: Dict[str, Any],
) -> None:
    available_names = {
        tool.get("schema", {}).get("function", {}).get("name", "")
        for tool in available_tools
    }
    if "maps_search_detail" not in available_names:
        return
    for restaurant in restaurants:
        if (
            restaurant.get("latitude") is not None
            and restaurant.get("longitude") is not None
        ):
            continue
        place_id = str(restaurant.get("place_id") or "")
        poi_id = place_id.removeprefix("amap:poi:")
        if not poi_id or poi_id == place_id:
            continue
        try:
            detail = await execute_tool(
                "maps_search_detail",
                {"id": poi_id},
                available_tools=available_tools,
                node_name=_NODE_NAME,
                activation_source="amap_dining_detail",
                **tool_context,
            )
        except Exception:
            logger.warning(
                "[destination_researcher] amap dining detail failed for %s",
                poi_id,
                exc_info=True,
            )
            continue
        if not isinstance(detail, dict):
            continue
        location: Any = None
        sanitized = detail.get("sanitized_result")
        if isinstance(sanitized, dict):
            location = sanitized.get("location")
        if location is None:
            text = _extract_amap_tool_text(detail)
            if text:
                try:
                    location = json.loads(text).get("location")
                except (json.JSONDecodeError, AttributeError):
                    location = None
        latitude, longitude = amap_location_to_wgs84(location)
        if latitude is not None and longitude is not None:
            restaurant["latitude"] = latitude
            restaurant["longitude"] = longitude


def _cn_only_destination_boundaries(
    destination_boundaries: List[Dict[str, Any]],
) -> bool:
    if not destination_boundaries:
        return False
    return all(
        str(boundary.get("country_code") or "").casefold() == "cn"
        for boundary in destination_boundaries
    )


async def discover_amap_dining(
    *,
    messages: List[Dict[str, Any]],
    available_tools: List[Dict[str, Any]],
    destination_boundaries: List[Dict[str, Any]],
    tool_context: Dict[str, Any],
    authoritative_tool_results: List[Dict[str, Any]],
    query_text: str,
) -> bool:
    """Deterministically ground CN dining from real amap POI data."""
    if not _cn_only_destination_boundaries(destination_boundaries):
        return False
    available_names = {
        tool.get("schema", {}).get("function", {}).get("name", "")
        for tool in available_tools
    }
    if "maps_text_search" not in available_names:
        logger.info(
            "[destination_researcher] amap dining skip: maps_text_search absent"
        )
        return False

    injected_any = False
    for boundary in destination_boundaries:
        city_hint = str(boundary.get("name") or "").strip()
        if not city_hint:
            continue
        try:
            env = await execute_tool(
                "maps_text_search",
                {"keywords": query_text, "city": city_hint},
                available_tools=available_tools,
                node_name=_NODE_NAME,
                activation_source="amap_dining_search",
                **tool_context,
            )
        except Exception:
            logger.warning(
                "[destination_researcher] amap dining discovery failed for %s",
                city_hint,
                exc_info=True,
            )
            continue
        if not isinstance(env, dict) or env.get("status") != "success":
            logger.info(
                "[destination_researcher] amap dining search for %s status=%s",
                city_hint,
                env.get("status") if isinstance(env, dict) else type(env).__name__,
            )
            continue
        sanitized = env.get("sanitized_result")
        records = sanitized.get("results") if isinstance(sanitized, dict) else None
        if isinstance(records, list):
            restaurants = _restaurants_from_pois(records)
        else:
            restaurants = _parse_amap_restaurants(_extract_amap_tool_text(env))
        await _enrich_amap_dining_coordinates(
            restaurants,
            available_tools=available_tools,
            tool_context=tool_context,
        )

        annotate_destination_distance(
            restaurants,
            destination_latitude=boundary.get("latitude"),
            destination_longitude=boundary.get("longitude"),
        )
        audit_id = str(env.get("audit_id") or "").strip()
        logger.info(
            "[destination_researcher] amap dining for %s: %d POIs, audit_id=%s",
            city_hint,
            len(restaurants),
            bool(audit_id),
        )
        if not restaurants or not audit_id:
            continue
        retrieved_at = str(
            env.get("retrieved_at")
            or datetime.datetime.now(datetime.timezone.utc).isoformat()
        )
        identity_envelope = _build_amap_dining_identity_envelope(
            results=restaurants,
            audit_id=audit_id,
            retrieved_at=retrieved_at,
        )
        messages.append(
            {
                "role": "tool",
                "content": compact_tool_content_for_model(identity_envelope),
            }
        )
        authoritative_tool_results.append(identity_envelope)
        injected_any = True
        logger.info(
            "[destination_researcher] deterministic amap dining bound: %d for %s (e.g. %s)",
            len(restaurants),
            city_hint,
            restaurants[0]["name"],
        )

    if not injected_any:
        return False
    return has_required_provider_place_selection(
        authoritative_tool_messages(authoritative_tool_results),
        expected_worker=_NODE_NAME,
        required_candidate_kinds=["dining"],
    )
