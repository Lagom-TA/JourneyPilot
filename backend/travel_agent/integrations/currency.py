"""Integrations currency."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Mapping
from typing import Optional
import httpx
import logging
import re
import time


logger = logging.getLogger(__name__)


FRANKFURTER_BASE_URL = "https://api.frankfurter.dev/v1"


CANONICAL_CURRENCY = "CNY"


_CURRENCY_CODE = re.compile(r"^[A-Z]{3}$")


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


_RATE_CACHE_TTL_SECONDS = 3600.0


_rate_cache: dict[str, tuple[float, str, float]] = {}


class CurrencyConversionUnavailable(RuntimeError):
    """The rate this conversion needs was not published or not reachable."""


@dataclass(frozen=True)
class ConvertedAmount:
    """One Provider amount in CNY, plus everything needed to re-derive it."""

    amount_cny: float
    source_amount: float
    source_currency: str
    rate_to_cny: float

    rate_date: Optional[str]


def _default_client() -> httpx.AsyncClient:
    """The client used when a caller injects none.

    Its own function so callers can supply a fake client for the network without
    taking injected clients away too, the same guard the two Redis-backed caches
    already have.
    """

    return httpx.AsyncClient(timeout=httpx.Timeout(15.0))


def reset_rate_cache() -> None:
    """Forget every cached rate (tests, and any process that must re-fetch)."""

    _rate_cache.clear()


def _currency_code(value: object) -> str:
    code = str(value or "").strip().upper()
    if not _CURRENCY_CODE.fullmatch(code):
        raise CurrencyConversionUnavailable(
            f"{value!r} is not one ISO 4217 three-letter currency code"
        )
    return code


async def _fetch_rate_to_cny(code: str, client: httpx.AsyncClient) -> tuple[float, str]:
    try:
        response = await client.get(
            f"{FRANKFURTER_BASE_URL}/latest",
            params={"base": code, "symbols": CANONICAL_CURRENCY},
        )
        response.raise_for_status()
        payload: Any = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise CurrencyConversionUnavailable(
            f"no reachable {code}->{CANONICAL_CURRENCY} rate publisher"
        ) from exc
    rates = payload.get("rates") if isinstance(payload, Mapping) else None
    raw_rate = rates.get(CANONICAL_CURRENCY) if isinstance(rates, Mapping) else None
    if (
        not isinstance(raw_rate, (int, float))
        or isinstance(raw_rate, bool)
        or float(raw_rate) <= 0
    ):
        raise CurrencyConversionUnavailable(
            f"rate publisher quotes no {code}->{CANONICAL_CURRENCY} rate"
        )
    rate_date = str(payload.get("date") or "").strip()
    if not _ISO_DATE.fullmatch(rate_date):
        raise CurrencyConversionUnavailable(
            f"{code}->{CANONICAL_CURRENCY} rate carries no publisher date"
        )
    return float(raw_rate), rate_date


async def convert_to_cny(
    amount: object,
    currency: object,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> ConvertedAmount:
    """Express one Provider amount in CNY at the latest published rate.

    Raises ``CurrencyConversionUnavailable`` rather than returning ``None``: the
    caller has to decide what an unconvertible quote means for its own contract,
    and a ``None`` that looks like "the supplier quoted nothing" is exactly the
    confusion this module must not create.
    """

    try:
        value = float(amount)
    except (TypeError, ValueError) as exc:
        raise CurrencyConversionUnavailable(f"{amount!r} is not an amount") from exc
    if value < 0:
        raise CurrencyConversionUnavailable("a Provider amount cannot be negative")
    code = _currency_code(currency)
    if code == CANONICAL_CURRENCY:
        return ConvertedAmount(
            amount_cny=round(value, 2),
            source_amount=value,
            source_currency=code,
            rate_to_cny=1.0,
            rate_date=None,
        )
    now = time.monotonic()
    cached = _rate_cache.get(code)
    if cached is not None and now - cached[2] < _RATE_CACHE_TTL_SECONDS:
        rate, rate_date = cached[0], cached[1]
    else:
        owns_client = client is None
        active_client = client or _default_client()
        try:
            rate, rate_date = await _fetch_rate_to_cny(code, active_client)
        finally:
            if owns_client:
                await active_client.aclose()
        _rate_cache[code] = (rate, rate_date, now)
        logger.info(
            "[currency] %s->%s rate %s dated %s from Frankfurter",
            code,
            CANONICAL_CURRENCY,
            rate,
            rate_date,
        )
    return ConvertedAmount(
        amount_cny=round(value * rate, 2),
        source_amount=value,
        source_currency=code,
        rate_to_cny=rate,
        rate_date=rate_date,
    )
