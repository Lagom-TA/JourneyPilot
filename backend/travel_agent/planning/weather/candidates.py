from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.references import EntityRef, EntityType, TransportLegRef
from travel_agent.planning.research.candidates import (
    ResearchCandidate,
    TransportCandidate,
)
from travel_agent.planning.weather.models import WeatherDayContext


def _target_ref(candidate: ResearchCandidate) -> EntityRef | TransportLegRef:
    if candidate.candidate_kind == "transport":
        return TransportLegRef(transport_leg_id=candidate.candidate_id)
    entity_type = {
        "visit": EntityType.VISIT_STOP,
        "dining": EntityType.DINING_STOP,
        "lodging": EntityType.LODGING_STAY,
    }[candidate.candidate_kind]
    return EntityRef(entity_type=entity_type, entity_id=candidate.candidate_id)


def _weather_days(
    state: TravelAgentState, candidate: ResearchCandidate
) -> list[WeatherDayContext]:
    if state.weather_context is None:
        return []
    destination_days = sorted(
        [
            day
            for day in state.weather_context.days
            if day.destination_id == candidate.destination_id
        ],
        key=lambda day: day.date,
    )
    if not isinstance(candidate, TransportCandidate):
        return destination_days

    scheduled_days = [
        day
        for day in destination_days
        if _transport_applies_to_weather_day(candidate, day)
    ]
    if candidate.departure_at is not None or candidate.arrival_at is not None:
        return [
            _scheduled_transport_weather_day(candidate, day) for day in scheduled_days
        ]
    if candidate.transport_class == "long_distance":
        return [
            day
            for day in destination_days
            if day.date == state.weather_context.trip_start_date
        ]
    return destination_days


def _weather_zone(day: WeatherDayContext) -> ZoneInfo | None:
    if not day.timezone:
        return None
    try:
        return ZoneInfo(day.timezone)
    except ZoneInfoNotFoundError:
        return None


def _local_timestamp(
    timestamp: datetime | None,
    day: WeatherDayContext,
) -> datetime | None:
    if timestamp is None:
        return None
    if timestamp.utcoffset() is None:
        return None
    zone = _weather_zone(day)
    if zone is None:
        return timestamp
    return timestamp.astimezone(zone)


def _transport_applies_to_weather_day(
    candidate: TransportCandidate,
    day: WeatherDayContext,
) -> bool:
    """Bind destination weather to the route's actual local service date."""
    if candidate.transport_class == "long_distance":
        anchor = candidate.arrival_at or candidate.departure_at
        local_anchor = _local_timestamp(anchor, day)
        return local_anchor is not None and local_anchor.date() == day.date

    start = _local_timestamp(candidate.departure_at, day)
    end = _local_timestamp(candidate.arrival_at, day)
    if start is None and end is None:
        return False
    start = start or end
    end = end or start
    return start.date() <= day.date <= end.date()


def _scheduled_transport_weather_day(
    candidate: TransportCandidate,
    day: WeatherDayContext,
) -> WeatherDayContext:
    """Narrow a forecast day to the hourly window relevant to a route."""
    if day.data_kind != "forecast" or not day.hourly_windows:
        return day

    if candidate.transport_class == "long_distance":
        anchor = _local_timestamp(candidate.arrival_at or candidate.departure_at, day)
        relevant = [
            window
            for window in day.hourly_windows
            if anchor is not None and window.start_at <= anchor < window.end_at
        ]
    else:
        start = _local_timestamp(candidate.departure_at, day)
        end = _local_timestamp(candidate.arrival_at, day)
        relevant = [
            window
            for window in day.hourly_windows
            if start is not None
            and end is not None
            and window.start_at < end
            and window.end_at > start
        ]
    if not relevant:
        return day

    probabilities = [
        item.precipitation_probability_pct
        for item in relevant
        if item.precipitation_probability_pct is not None
    ]
    apparent_temperatures = [
        item.apparent_temperature_c
        for item in relevant
        if item.apparent_temperature_c is not None
    ]
    wind_speeds = [
        item.wind_speed_kph for item in relevant if item.wind_speed_kph is not None
    ]
    return day.model_copy(
        update={
            "condition_code": None,
            "condition_label": None,
            "high_c": None,
            "low_c": None,
            "apparent_high_c": (
                max(apparent_temperatures) if apparent_temperatures else None
            ),
            "precipitation_probability_pct": (
                max(probabilities) if probabilities else None
            ),
            "precipitation_mm": None,
            "wind_speed_kph": max(wind_speeds) if wind_speeds else None,
            "wind_gust_kph": None,
            "hourly_windows": relevant,
        }
    )
