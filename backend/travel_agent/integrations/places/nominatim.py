"""Integrations places nominatim."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from travel_agent.config.loader import get_settings
from travel_agent.integrations.places.contracts import NominatimPlaceSearchError
from travel_agent.integrations.places.contracts import NominatimSearchObservation
from travel_agent.integrations.places.normalization import normalize_country_code
from travel_agent.integrations.places.retry import _RATE_GATE
from travel_agent.integrations.places.retry import _send_with_retry
from travel_agent.integrations.places.normalization import _is_coordinate
from travel_agent.integrations.places.normalization import destination_focus_viewbox
from travel_agent.storage.place_search_cache import _SEARCH_CACHE
from travel_agent.storage.place_search_cache import _search_cache_digest
from typing import Any
from typing import Dict
from typing import Optional
import httpx
import re


async def search_nominatim_raw(
    query: str,
    *,
    country_code: Optional[str] = None,
    limit: int = 5,
    focus_latitude: Optional[float] = None,
    focus_longitude: Optional[float] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> NominatimSearchObservation:
    """Return the complete bounded provider response for one global place query.

    Every caller of the ``/search`` endpoint goes through here — the intake
    route, the authored-place ladder and the ``global_place_search`` tool — so
    this is where reuse belongs. The answer carries its own ``observed_at``: a
    reused body reports the instant the provider produced it, and the caller is
    responsible for publishing that instead of ``now``.

    ``focus_latitude`` / ``focus_longitude`` are the controlled destination's own
    provider point, when the caller has one.  They become a soft
    :func:`destination_focus_viewbox`, which is why they belong here and not at
    each call site: the box is derived from the point exactly once, and the two
    callers that hold a destination point (the ``global_place_search`` tool and
    the authored-place ladder) cannot end up focusing differently.  The intake
    route is the caller that legitimately has none — it is the request that
    *resolves* the destination, so there is no destination to focus on yet.

    Half a point is not a point: a lone latitude focuses nothing rather than
    silently focusing on the prime meridian.
    """
    normalized_query = " ".join((query or "").split())
    if not normalized_query:
        raise ValueError("query is required")
    if not 1 <= limit <= 10:
        raise ValueError("limit must be between 1 and 10")
    normalized_country = normalize_country_code(country_code)
    settings = get_settings().geocoding
    params: Dict[str, Any] = {
        "q": normalized_query,
        "format": "jsonv2",
        "addressdetails": 1,
        "namedetails": 1,
        "limit": limit,
        "accept-language": "zh-CN,zh,en",
    }
    if normalized_country is not None:
        params["countrycodes"] = normalized_country
    if _is_coordinate(focus_latitude) and _is_coordinate(focus_longitude):
        params["viewbox"] = destination_focus_viewbox(
            float(focus_latitude), float(focus_longitude)
        )
    base_url = settings.nominatim_base_url.rstrip("/")
    digest = _search_cache_digest(base_url, params)

    cached = await _SEARCH_CACHE.get(digest)
    if cached is not None:
        return cached
    owns_client = client is None
    resolved_client = client or httpx.AsyncClient(
        timeout=settings.search_timeout_seconds,
        headers={"User-Agent": settings.user_agent},
    )
    try:
        response = await _send_with_retry(
            lambda: resolved_client.get(
                f"{base_url}/search",
                params=params,
            ),
            rate_gate=_RATE_GATE,
            min_interval_seconds=settings.min_interval_seconds,
            unavailable_message="global place provider unavailable",
        )
        raw = response.json()
    except ValueError as exc:
        raise NominatimPlaceSearchError(
            "global place provider returned a non-JSON body",
            code="provider_unparseable",
        ) from exc
    finally:
        if owns_client:
            await resolved_client.aclose()
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise NominatimPlaceSearchError(
            "global place provider returned an invalid payload",
            code="provider_invalid_payload",
        )
    observation = NominatimSearchObservation(
        items=[dict(item) for item in raw],
        observed_at=datetime.now(timezone.utc),
        origin="live",
    )
    await _SEARCH_CACHE.set(digest, observation)
    return observation


async def lookup_nominatim_osm_ids(
    osm_ids: list[str],
    *,
    accept_language: Optional[str] = "zh-CN,zh,en",
    client: Optional[httpx.AsyncClient] = None,
) -> list[Dict[str, Any]]:
    """Fetch complete address/country/type facts for exact OSM identities.

    ``accept_language`` is the provider's own parameter name: the default is the
    identity posture the rest of the pipeline stores places under, ``None`` omits
    the parameter so the provider answers in each place's local script.
    """
    if not osm_ids:
        return []
    settings = get_settings().geocoding
    owns_client = client is None
    resolved_client = client or httpx.AsyncClient(
        timeout=settings.timeout_seconds,
        headers={"User-Agent": settings.user_agent},
    )
    params: Dict[str, Any] = {
        "osm_ids": ",".join(osm_ids),
        "format": "jsonv2",
        "addressdetails": 1,
        "namedetails": 1,
    }
    if accept_language:
        params["accept-language"] = accept_language
    try:
        response = await _send_with_retry(
            lambda: resolved_client.get(
                f"{settings.nominatim_base_url.rstrip('/')}/lookup",
                params=params,
            ),
            rate_gate=_RATE_GATE,
            min_interval_seconds=settings.min_interval_seconds,
            unavailable_message="global place identity lookup unavailable",
        )
        payload = response.json()
    except ValueError as exc:
        raise NominatimPlaceSearchError(
            "global place identity lookup returned a non-JSON body",
            code="provider_unparseable",
        ) from exc
    finally:
        if owns_client:
            await resolved_client.aclose()
    if not isinstance(payload, list) or any(
        not isinstance(item, dict) for item in payload
    ):
        raise NominatimPlaceSearchError(
            "global place identity lookup returned invalid data",
            code="provider_invalid_payload",
        )
    return [dict(item) for item in payload]


_OSM_PLACE_ID = re.compile(
    r"^osm:(?P<osm_type>node|way|relation):(?P<osm_id>[1-9]\d*)$"
)


_OSM_LOOKUP_PREFIXES = {"node": "N", "way": "W", "relation": "R"}


def osm_lookup_id(place_id: str) -> Optional[str]:
    """Convert a stable ``osm:{type}:{id}`` place_id into a ``/lookup`` token.

    The inverse of ``stable_place_id_osm``; non-OSM namespaces (12306, amap POI)
    have no OSM object and fail closed with None.
    """
    match = _OSM_PLACE_ID.fullmatch(str(place_id or "").strip())
    if match is None:
        return None
    return f"{_OSM_LOOKUP_PREFIXES[match.group('osm_type')]}{match.group('osm_id')}"


async def lookup_typed_addresses_bilingual(
    place_ids: list[str],
) -> Dict[str, list[Dict[str, Any]]]:
    """Return each place's typed ``address`` dicts in local script and in English.

    Two batched provider calls total, whatever the number of places: one without
    ``accept-language`` (each place answers in its own script) and one pinned to
    English.  Callers need both because a locality name only helps cross-checking
    an external page when it is spelled the way that page spells it — a Paris
    review page writes "Rue Saint-Dominique", never the zh-CN "圣多米尼克路" the
    stored identity carries.

    Provider failures propagate as ``NominatimPlaceSearchError``: an empty answer
    and an unavailable provider are different facts, and the caller decides.
    """
    lookup_ids: Dict[str, str] = {}
    for place_id in place_ids:
        token = osm_lookup_id(place_id)
        if token is not None and token not in lookup_ids:
            lookup_ids[token] = str(place_id)
    if not lookup_ids:
        return {}
    typed: Dict[str, list[Dict[str, Any]]] = {
        place_id: [] for place_id in lookup_ids.values()
    }
    tokens = list(lookup_ids)
    for accept_language in (None, "en"):
        for item in await lookup_nominatim_osm_ids(
            tokens,
            accept_language=accept_language,
        ):
            prefix = _OSM_LOOKUP_PREFIXES.get(
                str(item.get("osm_type") or "").strip().casefold()
            )
            address = item.get("address")
            if prefix is None or not isinstance(address, dict):
                continue
            place_id = lookup_ids.get(f"{prefix}{item.get('osm_id')}")
            if place_id is None:
                continue
            typed[place_id].append(dict(address))
    return typed
