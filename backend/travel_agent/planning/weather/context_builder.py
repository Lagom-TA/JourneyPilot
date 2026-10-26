"""天气上下文构建。"""

from __future__ import annotations

from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pydantic import Field
from travel_agent.integrations.weather import ProviderWeatherDay
from travel_agent.integrations.weather import WeatherProvider
from travel_agent.integrations.weather import WeatherProviderError
from travel_agent.integrations.weather import WeatherProviderRequest
from travel_agent.integrations.weather import WeatherProviderResponse
from travel_agent.planning.research.evidence import FactAssertion
from travel_agent.planning.research.evidence import FieldProvenance
from travel_agent.planning.research.evidence import SourceRecord
from travel_agent.planning.weather.fact_binding import _fact_lineage
from travel_agent.planning.weather.fact_binding import _source_record
from travel_agent.planning.weather.models import WeatherContextSnapshot
from travel_agent.planning.weather.models import WeatherCoverage
from travel_agent.planning.weather.models import WeatherDayContext
from travel_agent.schema import StrictModel
from typing import Awaitable
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence
import asyncio


class WeatherContextBuildResult(StrictModel):
    weather_snapshot: WeatherContextSnapshot
    source_records: List[SourceRecord] = Field(default_factory=list)
    fact_assertions: List[FactAssertion] = Field(default_factory=list)
    field_provenance: List[FieldProvenance] = Field(default_factory=list)


def _dates(start: date, end: date) -> List[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


class WeatherContextBuilder:
    """按顺序查询 provider，并物化预报日与不可用日。

    构建器不会生成季节基线；基线必须来自另一个有资质的天气 provider，才能表示
    为事实。
    """

    def __init__(
        self,
        providers: Sequence[WeatherProvider],
        *,
        max_retries_per_provider: int = 2,
        retry_backoff_seconds: float = 0.25,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Optional[Callable[[], datetime]] = None,
    ) -> None:
        if not providers:
            raise ValueError("weather context builder requires at least one provider")
        if max_retries_per_provider < 0:
            raise ValueError("weather provider retries cannot be negative")
        self._providers = list(providers)
        self._max_retries = max_retries_per_provider
        self._retry_backoff = retry_backoff_seconds
        self._sleep = sleep
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def build(
        self,
        *,
        requests: Sequence[WeatherProviderRequest],
        weather_data_revision: int,
        trip_start_date: date,
        trip_end_date: date,
    ) -> WeatherContextBuildResult:
        if trip_end_date < trip_start_date:
            raise ValueError("trip end date must not precede start date")
        if not requests:
            raise ValueError(
                "weather context requires at least one destination request"
            )
        destination_ids = [request.destination_id for request in requests]
        if len(destination_ids) != len(set(destination_ids)):
            raise ValueError("weather requests must contain unique destination ids")
        if any(
            request.start_date < trip_start_date or request.end_date > trip_end_date
            for request in requests
        ):
            raise ValueError("destination weather request falls outside trip range")

        days: List[WeatherDayContext] = []
        coverage: List[WeatherCoverage] = []
        sources: List[SourceRecord] = []
        assertions: List[FactAssertion] = []
        provenance: List[FieldProvenance] = []
        retrieved_times: List[datetime] = []

        for request in requests:
            responses = await self._fetch_with_fallback(request)
            expected_dates = _dates(request.start_date, request.end_date)
            provider_days: Dict[
                date, tuple[ProviderWeatherDay, WeatherProviderResponse, SourceRecord]
            ] = {}
            available_dates: List[date] = []
            unavailable_dates: List[date] = []
            for response in responses:
                source = _source_record(request, response)
                sources.append(source)
                retrieved_times.append(response.retrieved_at)
                for item in response.days:
                    if item.has_facts() and item.date not in provider_days:
                        provider_days[item.date] = (item, response, source)

            for day_date in expected_dates:
                provider_result = provider_days.get(day_date)
                if provider_result is None:
                    unavailable_dates.append(day_date)
                    days.append(
                        WeatherDayContext(
                            destination_id=request.destination_id,
                            date=day_date,
                            timezone=request.timezone,
                            latitude=request.latitude,
                            longitude=request.longitude,
                            data_kind="unavailable",
                        )
                    )
                    continue
                provider_day, response, source = provider_result
                day_assertions, day_provenance = _fact_lineage(
                    request=request,
                    day=provider_day,
                    source=source,
                    response=response,
                )
                available_dates.append(day_date)
                assertions.extend(day_assertions)
                provenance.extend(day_provenance)
                days.append(
                    WeatherDayContext(
                        destination_id=request.destination_id,
                        date=day_date,
                        timezone=response.timezone,
                        latitude=request.latitude,
                        longitude=request.longitude,
                        data_kind=response.data_kind,
                        condition_code=provider_day.condition_code,
                        condition_label=provider_day.condition_label,
                        high_c=provider_day.high_c,
                        low_c=provider_day.low_c,
                        apparent_high_c=provider_day.apparent_high_c,
                        precipitation_probability_pct=provider_day.precipitation_probability_pct,
                        precipitation_mm=provider_day.precipitation_mm,
                        wind_speed_kph=provider_day.wind_speed_kph,
                        wind_gust_kph=provider_day.wind_gust_kph,
                        hourly_windows=provider_day.hourly_windows,
                        fact_assertion_ids=[
                            item.fact_assertion_id for item in day_assertions
                        ],
                    )
                )
            status = (
                "complete"
                if available_dates and not unavailable_dates
                else "partial"
                if available_dates
                else "unavailable"
            )
            coverage.append(
                WeatherCoverage(
                    destination_id=request.destination_id,
                    start_date=request.start_date,
                    end_date=request.end_date,
                    status=status,
                    available_dates=available_dates,
                    unavailable_dates=unavailable_dates,
                )
            )

        return WeatherContextBuildResult(
            weather_snapshot=WeatherContextSnapshot(
                weather_data_revision=weather_data_revision,
                trip_start_date=trip_start_date,
                trip_end_date=trip_end_date,
                days=days,
                coverage=coverage,
                retrieved_at=max(retrieved_times, default=self._now()),
            ),
            source_records=sources,
            fact_assertions=assertions,
            field_provenance=provenance,
        )

    async def _fetch_with_fallback(
        self, request: WeatherProviderRequest
    ) -> List[WeatherProviderResponse]:
        expected_dates = set(_dates(request.start_date, request.end_date))
        covered_dates: set[date] = set()
        responses: List[WeatherProviderResponse] = []
        for provider in self._providers:
            for attempt in range(self._max_retries + 1):
                try:
                    response = await provider.fetch_weather(request)
                    responses.append(response)
                    covered_dates.update(
                        day.date for day in response.days if day.has_facts()
                    )
                    break
                except WeatherProviderError as exc:
                    if not exc.retryable or attempt >= self._max_retries:
                        break
                    await self._sleep(self._retry_backoff * (2**attempt))
            if expected_dates <= covered_dates:
                break
        return responses
