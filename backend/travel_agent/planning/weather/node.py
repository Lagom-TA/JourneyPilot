"""Planning weather node."""

from __future__ import annotations

from typing import Any, Dict, Optional

from langchain_core.runnables import RunnableConfig

from travel_agent.integrations.weather import (
    WeatherProviderRequest,
    default_weather_providers,
)
from travel_agent.planning.requirements.identity_contracts import ControlledTripIdentity
from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.weather.context_builder import WeatherContextBuilder
from travel_agent.planning.weather.geography_contracts import DestinationGeoPoint


def destination_geo_resolver_node(state: TravelAgentState) -> Dict[str, Any]:
    """Use confirmed PlaceIdentity coordinates; never re-geocode or guess destinations."""

    identity = ControlledTripIdentity.model_validate(state.controlled_trip_identity)
    existing_timezones = {
        item.destination_id: item.timezone for item in state.destination_geo
    }
    destinations = [
        DestinationGeoPoint(
            destination_id=item.place_id,
            name=item.name,
            display_name=item.display_name,
            country_code=item.country_code,
            latitude=item.latitude,
            longitude=item.longitude,
            trip_start_date=identity.start_date,
            trip_end_date=identity.end_date,
            timezone=existing_timezones.get(item.place_id),
        )
        for item in identity.destinations
    ]
    return {"destination_geo": destinations}


def _configured_builder(config: Optional[RunnableConfig]) -> WeatherContextBuilder:
    configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
    injected = configurable.get("weather_context_builder")
    if injected is not None:
        return injected
    return WeatherContextBuilder(default_weather_providers())


async def weather_context_builder_node(
    state: TravelAgentState,
    config: Optional[RunnableConfig] = None,
) -> Dict[str, Any]:
    """Build one destination/date weather grid before any planning or research."""

    identity = ControlledTripIdentity.model_validate(state.controlled_trip_identity)
    if not state.destination_geo:
        raise ValueError("weather context requires resolved controlled destinations")
    expected_destination_ids = {item.destination_id for item in state.destination_geo}
    if (
        state.weather_context is not None
        and state.weather_context.trip_start_date == identity.start_date
        and state.weather_context.trip_end_date == identity.end_date
        and {item.destination_id for item in state.weather_context.coverage}
        == expected_destination_ids
    ):
        return {}
    requests = [
        WeatherProviderRequest(
            destination_id=item.destination_id,
            destination_name=item.display_name,
            latitude=item.latitude,
            longitude=item.longitude,
            timezone=item.timezone,
            start_date=item.trip_start_date,
            end_date=item.trip_end_date,
        )
        for item in state.destination_geo
    ]
    result = await _configured_builder(config).build(
        requests=requests,
        weather_data_revision=0,
        trip_start_date=identity.start_date,
        trip_end_date=identity.end_date,
    )
    resolved_timezones = {
        day.destination_id: day.timezone
        for day in result.weather_snapshot.days
        if day.timezone is not None
    }
    destination_geo = [
        item.model_copy(
            update={"timezone": resolved_timezones.get(item.destination_id)}
        )
        for item in state.destination_geo
    ]
    return {
        "destination_geo": destination_geo,
        "weather_context": result.weather_snapshot,
        "weather_source_records": result.source_records,
        "weather_fact_assertions": result.fact_assertions,
        "weather_field_provenance": result.field_provenance,
    }
