import httpx
import pytest

from travel_agent.integrations.currency import CurrencyConversionUnavailable, convert_to_cny


@pytest.mark.parametrize("amount", [float("nan"), float("inf"), -1, True, 10**1000])
async def test_non_finite_or_invalid_amount_is_rejected(amount):
    with pytest.raises(CurrencyConversionUnavailable):
        await convert_to_cny(amount, "CNY")


async def test_non_finite_provider_rate_is_rejected(monkeypatch):
    from travel_agent.integrations import currency

    monkeypatch.setattr(currency, "_rate_cache", {})
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, content=b'{"date":"2026-11-04","rates":{"CNY":NaN}}'
    ))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(CurrencyConversionUnavailable):
            await convert_to_cny(100, "JPY", client=client)
