"""Planning research place search."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from travel_agent.integrations.places.contracts import NominatimPlaceSearchError
from travel_agent.integrations.places.nominatim import search_nominatim_raw
from travel_agent.integrations.places.normalization import _CONCRETE_PLACE_FILTERS
from travel_agent.integrations.places.normalization import _OSM_RELATION_PLACE_ID
from travel_agent.integrations.places.normalization import logger
from travel_agent.integrations.places.normalization import normalize_country_code
from travel_agent.integrations.places.normalization import normalize_nominatim_place
from travel_agent.integrations.places.overpass import _bounded_aliases
from travel_agent.integrations.places.search import _IDENTITY_FALLBACK_BUDGET_SECONDS
from travel_agent.integrations.places.search import _resolve_identity_inside_relation
from travel_agent.planning.requirements.destination_scope import (
    annotate_destination_distance,
)
from typing import Any
from typing import Dict
from typing import Optional
import asyncio


async def global_place_search(
    query: str,
    country_code: str,
    limit: int = 5,
    destination_place_id: Optional[str] = None,
    destination_latitude: Optional[float] = None,
    destination_longitude: Optional[float] = None,
    candidate_kind: Optional[str] = None,
    aliases: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """Tool executor returning only identities inside the requested country.

    ``destination_latitude`` / ``destination_longitude`` must reach the primary text
    search, not just the Overpass rung below: the text search is the rung that actually
    answers, and without them it runs with no idea where the destination is.  Every
    caller already supplies them.
    """
    normalized_country = normalize_country_code(country_code)
    if normalized_country is None:
        raise ValueError("country_code is required")
    observation = await search_nominatim_raw(
        query,
        country_code=normalized_country,
        limit=limit,
        focus_latitude=destination_latitude,
        focus_longitude=destination_longitude,
    )
    results = [
        place
        for item in observation.items
        if (place := normalize_nominatim_place(item)) is not None
        and place["provider_country_code"] == normalized_country
    ]
    is_concrete = _CONCRETE_PLACE_FILTERS.get(candidate_kind or "")
    if is_concrete is not None:
        results = [place for place in results if is_concrete(place)]
    annotate_destination_distance(
        results,
        destination_latitude=destination_latitude,
        destination_longitude=destination_longitude,
    )
    resolution_method = "nominatim_text_search"
    identity_fallback_failure: Optional[Dict[str, str]] = None
    if (
        not results
        and is_concrete is not None
        and isinstance(destination_place_id, str)
    ):
        if _OSM_RELATION_PLACE_ID.fullmatch(destination_place_id.strip()) is None:
            message = (
                "destination_place_id is not a controlled osm relation: "
                f"{destination_place_id!r}"
            )
            logger.warning("global place identity fallback skipped: %s", message)
            identity_fallback_failure = {
                "provider": "overpass",
                "reason": "destination_place_id_not_controlled_relation",
                "message": message,
            }
        else:
            entity_names = _bounded_aliases(query, aliases)
            try:
                results = await asyncio.wait_for(
                    _resolve_identity_inside_relation(
                        entity_names,
                        candidate_kind=candidate_kind,
                        country_code=normalized_country,
                        destination_place_id=destination_place_id,
                        destination_latitude=destination_latitude,
                        destination_longitude=destination_longitude,
                        limit=limit,
                        is_concrete=is_concrete,
                    ),
                    timeout=_IDENTITY_FALLBACK_BUDGET_SECONDS,
                )
                resolution_method = "overpass_name_then_nominatim_identity"
            except asyncio.TimeoutError:
                logger.warning(
                    "global place identity fallback budget spent after %.1fs: kind=%s query=%r",
                    _IDENTITY_FALLBACK_BUDGET_SECONDS,
                    candidate_kind,
                    " ".join(query.split()),
                )
                identity_fallback_failure = {
                    "provider": "overpass",
                    "reason": "identity_fallback_budget_spent",
                    "message": (
                        "identity fallback exceeded "
                        f"{_IDENTITY_FALLBACK_BUDGET_SECONDS}s"
                    ),
                }
            except NominatimPlaceSearchError as exc:
                logger.warning(
                    "global place identity fallback unavailable: kind=%s query=%r: %s",
                    candidate_kind,
                    " ".join(query.split()),
                    exc,
                )
                identity_fallback_failure = {
                    "provider": "overpass",
                    "reason": "provider_unavailable",
                    "message": str(exc),
                }
    response = {
        "success": True,
        "provider": "nominatim",
        "resolution_method": resolution_method,
        "query": " ".join(query.split()),
        "requested_country_code": normalized_country,
        "destination_place_id": destination_place_id,
        "results": results,
    }
    if identity_fallback_failure is not None:
        response["identity_fallback_failure"] = identity_fallback_failure

    response["observed_at"] = observation.observed_at.isoformat()
    response["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    return response
