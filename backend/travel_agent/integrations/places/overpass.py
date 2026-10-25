"""Integrations places overpass."""

from __future__ import annotations

from travel_agent.config import get_settings
from travel_agent.integrations.places.contracts import NominatimPlaceSearchError
from travel_agent.integrations.places.normalization import _OSM_RELATION_PLACE_ID
from travel_agent.integrations.places.retry import _OVERPASS_RATE_GATE
from travel_agent.integrations.places.retry import _send_with_retry
from typing import Dict
from typing import Optional
import httpx
import json
import os
import re


_OVERPASS_TAG_FILTERS: Dict[str, tuple[str, ...]] = {
    "dining": ('["amenity"~"^(restaurant|cafe|fast_food|bar|pub|food_court)$"]',),
    "visit": (
        '["tourism"~"^(attraction|museum|gallery|artwork|viewpoint|theme_park|zoo|aquarium)$"]',
        '["historic"]',
        '["leisure"~"^(park|garden|nature_reserve|water_park)$"]',
        '["amenity"~"^(place_of_worship|theatre|arts_centre|marketplace)$"]',
        '["shop"~"^(mall|department_store)$"]',
    ),
}


def _bounded_aliases(query: str, aliases: Optional[list[str]]) -> list[str]:
    values = [query, *(aliases or [])]
    normalized = list(
        dict.fromkeys(
            " ".join(value.split())
            for value in values
            if isinstance(value, str) and 2 <= len(" ".join(value.split())) <= 120
        )
    )
    if not normalized:
        raise ValueError("at least one concrete entity name is required")
    return normalized[:4]


async def search_overpass_place_ids(
    entity_names: list[str],
    *,
    kind: str,
    destination_place_id: str,
    destination_latitude: Optional[float] = None,
    destination_longitude: Optional[float] = None,
    limit: int,
    client: Optional[httpx.AsyncClient] = None,
) -> list[str]:
    """Resolve named POIs of one kind inside one controlled OSM relation.

    Nominatim's text index matches a place's primary name; Overpass matches the
    localized and alternate name tags too, which is what a place written in
    another script than its OSM name needs.
    """
    tag_filter = _OVERPASS_TAG_FILTERS.get(kind)
    if tag_filter is None:
        raise ValueError(f"unsupported overpass place kind: {kind}")
    match = _OSM_RELATION_PLACE_ID.fullmatch(destination_place_id.strip())
    if match is None:
        raise ValueError(
            f"destination_place_id is not a controlled osm relation: {destination_place_id!r}"
        )

    regex = "|".join(
        r"\s*".join(re.escape(part) for part in name.split())
        for name in entity_names
        if name.strip()
    )
    regex_literal = json.dumps(regex, ensure_ascii=False)
    if (
        isinstance(destination_latitude, (int, float))
        and not isinstance(destination_latitude, bool)
        and isinstance(destination_longitude, (int, float))
        and not isinstance(destination_longitude, bool)
        and -90 <= destination_latitude <= 90
        and -180 <= destination_longitude <= 180
    ):
        south = max(-90.0, float(destination_latitude) - 0.75)
        north = min(90.0, float(destination_latitude) + 0.75)
        west = max(-180.0, float(destination_longitude) - 0.75)
        east = min(180.0, float(destination_longitude) + 0.75)
        spatial_filter = f"({south},{west},{north},{east})"
        area_prefix = ""
    else:
        spatial_filter = "(area.searchArea)"
        area_prefix = f"rel({match.group('relation_id')});map_to_area->.searchArea;"
    statements = "".join(
        f"nwr{spatial_filter}{tag}"
        f'[~"^(name|name:en|name:ja|name:zh|alt_name|official_name|brand)$"~{regex_literal},i];'
        for tag in tag_filter
    )
    query = (
        f"[out:json][timeout:25];{area_prefix}({statements});out center tags {limit};"
    )
    settings = get_settings().geocoding
    owns_client = client is None
    resolved_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(max(30.0, settings.timeout_seconds)),
        headers={"User-Agent": settings.user_agent},
    )
    try:
        response = await _send_with_retry(
            lambda: resolved_client.post(
                os.getenv(
                    "OVERPASS_API_URL",
                    "https://overpass-api.de/api/interpreter",
                ),
                data={"data": query},
            ),
            rate_gate=_OVERPASS_RATE_GATE,
            min_interval_seconds=settings.min_interval_seconds,
            unavailable_message="global place identity provider unavailable",
        )
        payload = response.json()
    except ValueError as exc:
        raise NominatimPlaceSearchError(
            "global place identity provider returned a non-JSON body",
            code="provider_unparseable",
        ) from exc
    finally:
        if owns_client:
            await resolved_client.aclose()
    elements = payload.get("elements") if isinstance(payload, dict) else None
    remark = payload.get("remark") if isinstance(payload, dict) else None
    if isinstance(remark, str) and remark.strip():
        raise NominatimPlaceSearchError(
            f"global place identity provider did not complete: {remark.strip()}",
            code="provider_unavailable",
        )
    if not isinstance(elements, list):
        raise NominatimPlaceSearchError(
            "global place identity provider returned invalid data",
            code="provider_invalid_payload",
        )
    prefixes = {"node": "N", "way": "W", "relation": "R"}
    osm_ids: list[str] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        prefix = prefixes.get(str(element.get("type") or ""))
        osm_id = element.get("id")
        if prefix is None or not isinstance(osm_id, int) or isinstance(osm_id, bool):
            continue
        stable_id = f"{prefix}{osm_id}"
        if stable_id not in osm_ids:
            osm_ids.append(stable_id)
        if len(osm_ids) == limit:
            break
    return osm_ids
