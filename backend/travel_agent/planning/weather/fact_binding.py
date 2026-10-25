"""Planning weather fact binding."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from travel_agent.integrations.weather import ProviderWeatherDay
from travel_agent.integrations.weather import WeatherProviderRequest
from travel_agent.integrations.weather import WeatherProviderResponse
from travel_agent.planning.references import EntityRef
from travel_agent.planning.references import EntityType
from travel_agent.planning.research.evidence import FactAssertion
from travel_agent.planning.research.evidence import FactSourceLink
from travel_agent.planning.research.evidence import FieldProvenance
from travel_agent.planning.research.evidence import SourceRecord
from typing import Dict
from typing import List
import hashlib
import json


class WeatherContextBuildError(ValueError):
    """Raised when provider evidence cannot form a truthful public source."""


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _fact_lineage(
    *,
    request: WeatherProviderRequest,
    day: ProviderWeatherDay,
    source: SourceRecord,
    response: WeatherProviderResponse,
) -> tuple[List[FactAssertion], List[FieldProvenance]]:
    entity = EntityRef(
        entity_type=EntityType.WEATHER_DAY,
        entity_id=f"weather:{request.destination_id}:{day.date.isoformat()}",
    )
    fields: Dict[str, object] = {
        "condition_code": day.condition_code,
        "high_c": day.high_c,
        "low_c": day.low_c,
        "apparent_high_c": day.apparent_high_c,
        "precipitation_probability_pct": day.precipitation_probability_pct,
        "precipitation_mm": day.precipitation_mm,
        "wind_speed_kph": day.wind_speed_kph,
        "wind_gust_kph": day.wind_gust_kph,
        "hourly_windows": [item.model_dump(mode="json") for item in day.hourly_windows]
        or None,
    }
    assertions: List[FactAssertion] = []
    provenance: List[FieldProvenance] = []
    for field_path, value in fields.items():
        if value is None:
            continue
        assertion_id = f"weather-fact-{_canonical_hash([entity.entity_id, field_path, value, source.source_record_id])[:24]}"
        assertion = FactAssertion(
            fact_assertion_id=assertion_id,
            entity_ref=entity,
            field_path=field_path,
            asserted_value=value,
            unit={
                "high_c": "celsius",
                "low_c": "celsius",
                "apparent_high_c": "celsius",
                "precipitation_probability_pct": "percent",
                "precipitation_mm": "millimeter",
                "wind_speed_kph": "kilometer_per_hour",
                "wind_gust_kph": "kilometer_per_hour",
            }.get(field_path),
            criticality="decision_critical",
            status="verified",
            observed_at=response.retrieved_at,
            effective_from=datetime.combine(
                day.date, datetime.min.time(), tzinfo=timezone.utc
            ),
            effective_to=datetime.combine(
                day.date, datetime.max.time(), tzinfo=timezone.utc
            ),
            expires_at=response.provider_valid_until,
            source_links=[
                FactSourceLink(
                    source_record_id=source.source_record_id,
                    relation="supports",
                    source_locator=(
                        f"seasonal_baseline[month={day.date.month:02d}].{field_path}"
                        if response.data_kind == "seasonal_baseline"
                        else f"daily[{day.date.isoformat()}].{field_path}"
                    ),
                )
            ],
        )
        assertions.append(assertion)
        provenance.append(
            FieldProvenance(
                origin="external_fact",
                entity_ref=entity,
                field_path=field_path,
                reference_ids=[assertion_id],
            )
        )
    return assertions, provenance


def _source_record(
    request: WeatherProviderRequest,
    response: WeatherProviderResponse,
) -> SourceRecord:
    content_hash = _canonical_hash(response.raw_snapshot)
    source_id = f"weather-source-{_canonical_hash([request.destination_id, response.provider_name, content_hash])[:24]}"
    public_excerpt = (
        f"{request.destination_name} {request.start_date.isoformat()}–{request.end_date.isoformat()} "
        "weather forecast"
    )
    if response.data_kind == "seasonal_baseline":
        baseline = response.raw_snapshot.get("journeypilot_baseline")
        if not isinstance(baseline, dict):
            raise WeatherContextBuildError(
                "seasonal baseline source omitted its aggregation metadata"
            )
        aggregates = baseline.get("monthly_aggregates")
        if not isinstance(aggregates, dict) or not aggregates:
            raise WeatherContextBuildError(
                "seasonal baseline source omitted its monthly aggregates"
            )
        method = baseline.get("method")
        historical_start = str(baseline.get("historical_start") or "").strip()
        historical_end = str(baseline.get("historical_end") or "").strip()
        request_url = str(baseline.get("request_url") or "").strip()
        if method != "same_month_mean_over_complete_calendar_years":
            raise WeatherContextBuildError(
                "seasonal baseline source omitted its canonical aggregation method"
            )
        if not historical_start or not historical_end:
            raise WeatherContextBuildError(
                "seasonal baseline source omitted its historical interval"
            )
        if not request_url or request_url != response.canonical_url:
            raise WeatherContextBuildError(
                "seasonal baseline source URL does not match its exact provider request"
            )
        month_parts: list[str] = []
        for month, values in sorted(aggregates.items(), key=lambda item: int(item[0])):
            if not isinstance(values, dict):
                raise WeatherContextBuildError(
                    "seasonal baseline aggregate has an invalid public shape"
                )
            fact_parts = []
            for key, label, unit in (
                ("high_c", "高温", "°C"),
                ("low_c", "低温", "°C"),
                ("precipitation_mm", "降水", "mm"),
                ("wind_speed_kph", "风速", "km/h"),
            ):
                value = values.get(key)
                if isinstance(value, (int, float)):
                    fact_parts.append(f"{label} {value:g}{unit}")
            if fact_parts:
                month_parts.append(f"{int(month)} 月：{'、'.join(fact_parts)}")
        if not month_parts:
            raise WeatherContextBuildError(
                "seasonal baseline source omitted public aggregate values"
            )
        public_excerpt = (
            f"{request.destination_name}（{request.latitude:g}, {request.longitude:g}）；"
            f"历史样本 {historical_start} 至 {historical_end}；"
            f"按完整年份的同月日均值聚合；{'；'.join(month_parts)}。"
        )
    return SourceRecord(
        source_record_id=source_id,
        source_kind="external_tool",
        title=response.source_title,
        provider_name=response.provider_name,
        canonical_url=response.canonical_url,
        public_excerpt=public_excerpt,
        retrieved_at=response.retrieved_at,
        effective_from=datetime.combine(
            response.source_effective_from or request.start_date,
            datetime.min.time(),
            tzinfo=timezone.utc,
        ),
        effective_to=datetime.combine(
            response.source_effective_to or request.end_date,
            datetime.max.time(),
            tzinfo=timezone.utc,
        ),
        provider_valid_until=response.provider_valid_until,
        content_hash=content_hash,
        snapshot=response.raw_snapshot,
    )
