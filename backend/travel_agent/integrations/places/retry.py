"""Integrations places retry."""

from __future__ import annotations

from travel_agent.integrations.places.contracts import NominatimPlaceSearchError
from travel_agent.runtime.rate_gate import RateGate
from travel_agent.runtime.rate_gate import rate_gate_for
from typing import Optional
import httpx


_RATE_GATE = rate_gate_for("nominatim")


_OVERPASS_RATE_GATE = rate_gate_for("overpass")


_PROVIDER_MAX_ATTEMPTS = 2


_TRANSIENT_STATUS = frozenset({500, 502, 503, 504})


def _is_transient_provider_error(exc: httpx.HTTPError) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _TRANSIENT_STATUS

    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


async def _send_with_retry(
    send,
    *,
    rate_gate: RateGate,
    min_interval_seconds: float,
    unavailable_message: str,
) -> httpx.Response:
    """Run one rate-gated request, retrying only transient provider failures.

    The rate gate is the only spacing between attempts; see
    ``_PROVIDER_MAX_ATTEMPTS`` for why there is no second backoff on top of it.
    """
    last_exc: Optional[httpx.HTTPError] = None
    for attempt in range(_PROVIDER_MAX_ATTEMPTS):
        try:
            await rate_gate.acquire(min_interval_seconds)
            response = await send()
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            last_exc = exc
            if (
                _is_transient_provider_error(exc)
                and attempt + 1 < _PROVIDER_MAX_ATTEMPTS
            ):
                continue
            raise NominatimPlaceSearchError(
                unavailable_message, code="provider_unavailable"
            ) from exc
    raise NominatimPlaceSearchError(
        unavailable_message, code="provider_unavailable"
    ) from last_exc
