"""Planning research accommodation binding."""

from __future__ import annotations

import datetime
import json
import logging
from typing import Any, Dict, List, Mapping

from travel_agent.planning.requirements.destination_scope import (
    annotate_destination_distance,
)
from travel_agent.planning.research.accommodation.parsing import (
    _build_place_search_envelope,
    _extract_tool_text,
    _hotels_from_pois,
    _nominatim_hotels_from_results,
    _parse_amap_hotels,
)
from travel_agent.planning.research.accommodation.scope import _NODE_NAME
from travel_agent.tools.content import compact_tool_content_for_model
from travel_agent.tools.execution import execute_tool
from travel_agent.utils.coordinates import amap_location_to_wgs84

logger = logging.getLogger(__name__)


async def _enrich_amap_hotel_coordinates(
    hotels: List[Dict[str, Any]],
    *,
    available_tools: List[Dict[str, Any]],
    tool_context: Dict[str, Any],
) -> None:
    """Resolve each amap lodging POI's point geometry via maps_search_detail."""
    for hotel in hotels:
        if hotel.get("latitude") is not None and hotel.get("longitude") is not None:
            continue
        place_id = str(hotel.get("place_id") or "")
        poi_id = place_id.removeprefix("amap:poi:")
        if not poi_id or poi_id == place_id:
            continue
        try:
            detail = await execute_tool(
                "maps_search_detail",
                {"id": poi_id},
                available_tools=available_tools,
                node_name=_NODE_NAME,
                activation_source="amap_hotel_detail",
                **tool_context,
            )
        except Exception:
            logger.warning(
                "[accommodation_researcher] amap detail lookup failed for %s",
                poi_id,
                exc_info=True,
            )
            continue
        if not isinstance(detail, Mapping):
            continue
        location: Any = None
        sanitized = detail.get("sanitized_result")
        if isinstance(sanitized, Mapping):
            location = sanitized.get("location")
        if location is None:
            text = _extract_tool_text(detail)
            if text:
                try:
                    location = json.loads(text).get("location")
                except (json.JSONDecodeError, AttributeError):
                    location = None
        latitude, longitude = amap_location_to_wgs84(location)
        if latitude is not None and longitude is not None:
            hotel["latitude"] = latitude
            hotel["longitude"] = longitude


_NOMINATIM_PLACE_SEARCH_LIMIT = 10


async def _bind_amap_lodging(
    dest: Mapping[str, Any],
    *,
    messages: List[Dict[str, Any]],
    available_tools: List[Dict[str, Any]],
    tool_context: Dict[str, Any],
    authoritative_tool_results: List[Dict[str, Any]],
    query_text: str,
) -> bool:
    """Bind one CN destination's lodging identity from real amap POI data."""
    dest_name = str(dest.get("name") or "").strip()
    try:
        env = await execute_tool(
            "maps_text_search",
            {"keywords": query_text, "city": dest_name},
            available_tools=available_tools,
            node_name=_NODE_NAME,
            activation_source="amap_hotel_search",
            **tool_context,
        )
    except Exception:
        logger.warning(
            "[accommodation_researcher] amap hotel discovery failed for %s",
            dest_name,
            exc_info=True,
        )
        return False
    if not isinstance(env, Mapping) or env.get("status") != "success":
        logger.info(
            "[accommodation_researcher] amap search for %s returned status=%s error=%s",
            dest_name,
            (env.get("status") if isinstance(env, Mapping) else type(env).__name__),
            (env.get("error") if isinstance(env, Mapping) else None),
        )

        if isinstance(env, Mapping):
            authoritative_tool_results.append(dict(env))
        return False

    sanitized = env.get("sanitized_result")
    records = sanitized.get("results") if isinstance(sanitized, Mapping) else None
    if isinstance(records, list):
        hotels = _hotels_from_pois(records)
    else:
        hotels = _parse_amap_hotels(_extract_tool_text(env))

    await _enrich_amap_hotel_coordinates(
        hotels,
        available_tools=available_tools,
        tool_context=tool_context,
    )

    annotate_destination_distance(
        hotels,
        destination_latitude=dest.get("latitude"),
        destination_longitude=dest.get("longitude"),
    )
    audit_id = str(env.get("audit_id") or "").strip()
    logger.info(
        "[accommodation_researcher] amap search for %s: %d lodging POIs, audit_id=%s",
        dest_name,
        len(hotels),
        bool(audit_id),
    )
    if not hotels or not audit_id:
        return False
    retrieved_at = str(
        env.get("retrieved_at")
        or datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    envelope = _build_place_search_envelope(
        results=hotels,
        provider="amap",
        server_name="amap-maps",
        audit_id=audit_id,
        retrieved_at=retrieved_at,
    )
    messages.append(
        {"role": "tool", "content": compact_tool_content_for_model(envelope)}
    )
    authoritative_tool_results.append(envelope)
    logger.info(
        "[accommodation_researcher] deterministic amap lodging bound: %d hotels for %s (e.g. %s)",
        len(hotels),
        dest_name,
        hotels[0]["name"],
    )
    return True


async def _bind_nominatim_lodging(
    dest: Mapping[str, Any],
    *,
    messages: List[Dict[str, Any]],
    available_tools: List[Dict[str, Any]],
    tool_context: Dict[str, Any],
    authoritative_tool_results: List[Dict[str, Any]],
    query_text: str,
) -> bool:
    """Bind one non-CN destination's lodging identity from real Nominatim data."""
    dest_name = str(dest.get("name") or "").strip()
    country_code = str(dest.get("country_code") or "").strip().lower()
    if not dest_name or len(country_code) != 2:
        logger.info(
            "[accommodation_researcher] nominatim skip: incomplete destination identity %s",
            dest,
        )
        return False
    try:
        env = await execute_tool(
            "global_place_search",
            {
                "query": query_text,
                "country_code": country_code,
                "limit": _NOMINATIM_PLACE_SEARCH_LIMIT,
                "destination_latitude": dest.get("latitude"),
                "destination_longitude": dest.get("longitude"),
            },
            available_tools=available_tools,
            node_name=_NODE_NAME,
            activation_source="nominatim_hotel_search",
            allow_fallback=False,
            **tool_context,
        )
    except Exception:
        logger.warning(
            "[accommodation_researcher] nominatim hotel discovery failed for %s",
            dest_name,
            exc_info=True,
        )
        return False
    if not isinstance(env, Mapping) or env.get("status") != "success":
        logger.info(
            "[accommodation_researcher] nominatim search for %s returned status=%s",
            dest_name,
            (env.get("status") if isinstance(env, Mapping) else type(env).__name__),
        )
        return False
    sanitized = env.get("sanitized_result")
    records = sanitized.get("results") if isinstance(sanitized, Mapping) else None
    hotels = _nominatim_hotels_from_results(
        records if isinstance(records, list) else []
    )
    audit_id = str(env.get("audit_id") or "").strip()
    logger.info(
        "[accommodation_researcher] nominatim search for %s (%s): %d lodging places, audit_id=%s",
        dest_name,
        country_code,
        len(hotels),
        bool(audit_id),
    )
    if not hotels or not audit_id:
        return False
    retrieved_at = str(
        env.get("retrieved_at")
        or datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    envelope = _build_place_search_envelope(
        results=hotels,
        provider="nominatim",
        server_name="nominatim",
        audit_id=audit_id,
        retrieved_at=retrieved_at,
    )
    messages.append(
        {"role": "tool", "content": compact_tool_content_for_model(envelope)}
    )
    authoritative_tool_results.append(envelope)
    logger.info(
        "[accommodation_researcher] deterministic nominatim lodging bound: %d hotels for %s (e.g. %s)",
        len(hotels),
        dest_name,
        hotels[0]["name"],
    )
    return True
