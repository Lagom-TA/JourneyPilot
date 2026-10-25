from __future__ import annotations
from typing import Any
from travel_agent.integrations.weather import default_weather_providers
from travel_agent.planning.delivery.weather_refresh import WeatherBundleRefreshService
from travel_agent.planning.run_errors import DeliveryBundleMissing
from .context_builder import WeatherContextBuilder


async def refresh_delivery_weather(
    run_id: str,
    *,
    expected,
    refresh_id: str,
    bundle_store,
    trip_run_store,
    clock=None,
    weather_context_builder=None,
):

    if await bundle_store.get_current_bundle_id(run_id) is None:
        raise DeliveryBundleMissing()
    refresh_kwargs: dict[str, Any] = {}
    if clock is not None:
        refresh_kwargs["clock"] = clock
    service = WeatherBundleRefreshService(
        bundle_store,
        weather_context_builder or WeatherContextBuilder(default_weather_providers()),
        **refresh_kwargs,
    )
    result = await service.refresh_if_needed(
        run_id=run_id,
        expected=expected,
        idempotency_key=refresh_id,
        operation="weather_refresh_on_open",
    )

    if result.committed:
        manifest = result.bundle.manifest
        await trip_run_store.append_event_once(
            run_id,
            "bundle.current_changed",
            {
                "reason": "weather_refresh_on_open",
                "bundle_id": manifest.bundle_id,
                "manifest": manifest.model_dump(mode="json"),
            },
            idempotency_key=f"{run_id}:bundle_current_changed:{manifest.bundle_id}",
        )
    return result
