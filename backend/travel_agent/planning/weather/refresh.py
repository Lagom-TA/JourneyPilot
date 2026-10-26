"""天气快照与影响刷新。"""

from __future__ import annotations

from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from travel_agent.planning.delivery.bundle import DeliveryBundle
from travel_agent.planning.references import EntityRef
from travel_agent.planning.references import EntityType
from travel_agent.planning.research.evidence import FactStoreSnapshot
from travel_agent.planning.weather.context_builder import WeatherContextBuildResult
from travel_agent.planning.weather.impacts import WeatherImpactEngine
from travel_agent.planning.weather.models import WeatherContextSnapshot
from travel_agent.planning.weather.models import WeatherCoverage
from travel_agent.planning.weather.models import WeatherDayContext
from travel_agent.planning.workspace import TripWorkspaceV2
from typing import Callable
from typing import Iterable
import json
import logging


logger = logging.getLogger(__name__)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def expired_weather_destination_ids(
    bundle: DeliveryBundle,
    *,
    now: datetime,
    forecast_horizon_days: int = 16,
) -> set[str]:
    """返回需要执行相关刷新的目的地。"""
    now = _aware(now)
    assertion_index = {
        item.fact_assertion_id: item for item in bundle.fact_snapshot.fact_assertions
    }
    source_index = {
        item.source_record_id: item for item in bundle.fact_snapshot.source_records
    }
    stale: set[str] = set()
    horizon = now.date() + timedelta(days=forecast_horizon_days)
    for day in bundle.weather_snapshot.days:
        if day.data_kind == "seasonal_baseline":
            continue
        if day.data_kind == "unavailable":
            if now.date() <= day.date <= horizon:
                stale.add(day.destination_id)
            continue
        if not day.fact_assertion_ids:
            stale.add(day.destination_id)
            continue
        for assertion_id in day.fact_assertion_ids:
            assertion = assertion_index.get(assertion_id)
            if assertion is None or assertion.status != "verified":
                stale.add(day.destination_id)
                break
            if assertion.expires_at is not None and _aware(assertion.expires_at) <= now:
                stale.add(day.destination_id)
                break
            supporting_sources = [
                source_index.get(link.source_record_id)
                for link in assertion.source_links
                if link.relation == "supports"
            ]
            if not supporting_sources or all(
                source is None
                or source.provider_valid_until is None
                or (_aware(source.provider_valid_until) <= now)
                for source in supporting_sources
            ):
                stale.add(day.destination_id)
                break
    return stale


def _coverage(days: Iterable[WeatherDayContext]) -> list[WeatherCoverage]:
    grouped: dict[str, list[WeatherDayContext]] = {}
    for day in days:
        grouped.setdefault(day.destination_id, []).append(day)
    result: list[WeatherCoverage] = []
    for destination_id, items in grouped.items():
        items = sorted(items, key=lambda item: item.date)
        available = [item.date for item in items if item.data_kind != "unavailable"]
        unavailable = [item.date for item in items if item.data_kind == "unavailable"]
        status = (
            "complete"
            if available and not unavailable
            else "partial"
            if available
            else "unavailable"
        )
        result.append(
            WeatherCoverage(
                destination_id=destination_id,
                start_date=items[0].date,
                end_date=items[-1].date,
                status=status,
                available_dates=available,
                unavailable_dates=unavailable,
            )
        )
    return sorted(result, key=lambda item: item.destination_id)


def _merge_unique(
    items: Iterable[object], *, key: Callable[[object], str]
) -> list[object]:
    merged: dict[str, object] = {}
    for item in items:
        merged[key(item)] = item
    return list(merged.values())


def _fact_snapshot(
    bundle: DeliveryBundle,
    result: WeatherContextBuildResult,
) -> FactStoreSnapshot:
    sources = _merge_unique(
        [*bundle.fact_snapshot.source_records, *result.source_records],
        key=lambda item: item.source_record_id,
    )
    assertions = _merge_unique(
        [*bundle.fact_snapshot.fact_assertions, *result.fact_assertions],
        key=lambda item: item.fact_assertion_id,
    )
    provenance = _merge_unique(
        [*bundle.fact_snapshot.field_provenance, *result.field_provenance],
        key=lambda item: json.dumps(
            item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
        ),
    )
    return FactStoreSnapshot(
        fact_data_revision=bundle.manifest.fact_data_revision + 1,
        source_records=sources,
        fact_assertions=assertions,
        field_provenance=provenance,
    )


def _target_dates(
    bundle: DeliveryBundle,
) -> list[tuple[EntityRef, str, object, set[date]]]:
    itinerary = bundle.workspace.itinerary
    candidates = bundle.workspace.recommendation_catalog.candidate_index()
    day_dates = {
        day.day_id: day.date for day in itinerary.day_plans if day.date is not None
    }
    timeline_dates: dict[tuple[EntityType, str], set[date]] = {}
    for day in itinerary.day_plans:
        if day.date is None:
            continue
        for ref in day.timeline:
            timeline_dates.setdefault((ref.entity_type, ref.entity_id), set()).add(
                day.date
            )
    targets: list[tuple[EntityRef, str, object, set[date]]] = []
    entities = (
        [(EntityType.VISIT_STOP, item.item_id, item) for item in itinerary.visit_stops]
        + [
            (EntityType.DINING_STOP, item.item_id, item)
            for item in itinerary.dining_stops
        ]
        + [
            (EntityType.LODGING_STAY, item.stay_id, item)
            for item in itinerary.lodging_stays
        ]
        + [
            (EntityType.TRANSPORT_LEG, item.transport_leg_id, item)
            for item in itinerary.transport_legs
        ]
    )
    for entity_type, entity_id, entity in entities:
        candidate = candidates.get(entity.lineage.candidate_id)
        if candidate is None:
            continue
        dates = set(timeline_dates.get((entity_type, entity_id), set()))
        day_id = getattr(entity, "day_id", None)
        if day_id in day_dates:
            dates.add(day_dates[day_id])
        if entity_type == EntityType.LODGING_STAY:
            current = entity.check_in_date
            while current < entity.check_out_date:
                dates.add(current)
                current += timedelta(days=1)
        departure = getattr(entity, "departure_at", None)
        if departure is not None:
            dates.add(departure.date())
        targets.append(
            (
                EntityRef(entity_type=entity_type, entity_id=entity_id),
                candidate.destination_id,
                candidate.weather_sensitivity,
                dates,
            )
        )
    return targets


def _frozen_weather_impact_refs(bundle: DeliveryBundle) -> set[str]:
    """收集刷新后仍需保留的天气影响 ID。

    已物化实体的 lineage 与报告投影都引用旧影响 ID，候选目录中的候选也各自
    指向其评估时的影响记录；这些引用不会随刷新重算，刷新后的天气快照必须
    继续覆盖它们，Bundle 合同才不会因悬空引用拒绝提交。
    """

    refs: set[str] = set()
    itinerary = bundle.workspace.itinerary
    for entity in [
        *itinerary.visit_stops,
        *itinerary.dining_stops,
        *itinerary.lodging_stays,
        *itinerary.transport_legs,
    ]:
        refs.update(entity.lineage.weather_impact_ids)
    for candidate in bundle.workspace.recommendation_catalog.candidate_index().values():
        refs.update(candidate.weather_impact_ids)
    document = bundle.report_projection.document
    if document is not None:
        for day in document.days:
            for block in day.blocks:
                refs.update(block.weather_impact_ids)
    return refs


def _carry_over_frozen_impacts(
    bundle: DeliveryBundle, weather: WeatherContextSnapshot
) -> tuple[WeatherContextSnapshot, frozenset[str], frozenset[tuple[str, date]]]:
    """保留冻结记录仍引用的影响，并标出这些影响对应的 Day。

    影响 id 以目的地、日期、目标与 *条件* 为内容哈希；两次刷新之间条件消失会
    删掉行程据以构建的 id，Bundle 契约随即拒绝整次刷新。

    保留旧影响是如实的记账：冻结的 lineage 记录行程按什么条件规划，这是新预报
    不会改变的事实。支撑它的旧断言仍在合并后的事实快照中，引用不会悬空。

    同时返回每个保留影响的 ``(destination_id, date)``，取自上一快照自身的 Day；
    影响携带该 Day 的断言 id，因此匹配是精确的。投影据此判断某个 Day 展示的是
    沿用数据而非本次预报。
    """

    previous = {
        item.weather_impact_id: item for item in bundle.weather_snapshot.impacts
    }
    current = {item.weather_impact_id: item for item in weather.impacts}
    carried = {
        impact_id
        for impact_id in _frozen_weather_impact_refs(bundle)
        if impact_id not in current and impact_id in previous
    }
    if not carried:
        return weather, frozenset(), frozenset()
    day_keys: set[tuple[str, date]] = set()
    for impact_id in carried:
        impact = previous[impact_id]
        supporting = set(impact.fact_assertion_ids)
        for day in bundle.weather_snapshot.days:
            if day.date == impact.date and supporting & set(day.fact_assertion_ids):
                day_keys.add((day.destination_id, day.date))
    merged = {**current, **{impact_id: previous[impact_id] for impact_id in carried}}
    return (
        weather.model_copy(
            update={
                "impacts": sorted(
                    merged.values(), key=lambda item: item.weather_impact_id
                )
            }
        ),
        frozenset(carried),
        frozenset(day_keys),
    )


def _weather_snapshot(
    bundle: DeliveryBundle,
    result: WeatherContextBuildResult,
) -> tuple[WeatherContextSnapshot, bool, frozenset[tuple[str, date]]]:
    previous = {
        (item.destination_id, item.date): item for item in bundle.weather_snapshot.days
    }
    incoming = {
        (item.destination_id, item.date): item for item in result.weather_snapshot.days
    }
    used_previous = False
    retained: set[tuple[str, date]] = set()
    days: list[WeatherDayContext] = []
    for key in sorted(previous.keys() | incoming.keys()):
        new_day = incoming.get(key)
        old_day = previous.get(key)
        if (
            new_day is not None
            and new_day.data_kind == "unavailable"
            and old_day is not None
            and old_day.data_kind != "unavailable"
        ):
            days.append(old_day)
            used_previous = True
            retained.add(key)
        elif new_day is not None:
            days.append(new_day)
        elif old_day is not None:
            days.append(old_day)
            used_previous = True
            retained.add(key)

    impacts = []
    engine = WeatherImpactEngine()
    for target_ref, destination_id, sensitivity, target_dates in _target_dates(bundle):
        for day in days:
            if day.destination_id != destination_id:
                continue
            if target_dates and day.date not in target_dates:
                continue
            impacts.extend(
                engine.evaluate(
                    weather_day=day,
                    target_ref=target_ref,
                    sensitivity=sensitivity,
                )
            )
    impact_index = {item.weather_impact_id: item for item in impacts}
    return (
        WeatherContextSnapshot(
            weather_data_revision=bundle.manifest.weather_data_revision + 1,
            trip_start_date=bundle.weather_snapshot.trip_start_date,
            trip_end_date=bundle.weather_snapshot.trip_end_date,
            days=days,
            coverage=_coverage(days),
            impacts=sorted(
                impact_index.values(), key=lambda item: item.weather_impact_id
            ),
            retrieved_at=result.weather_snapshot.retrieved_at,
        ),
        used_previous,
        frozenset(retained),
    )


def _rebind_catalog_for_snapshot(
    bundle: DeliveryBundle,
    *,
    facts: FactStoreSnapshot,
    weather: WeatherContextSnapshot,
) -> tuple[TripWorkspaceV2, WeatherContextSnapshot]:
    """把工作区与候选目录对齐到新的事实与天气数据版本。

    目录与 packet 的 fact_data_revision 提升到新快照的版本。候选与行程内容
    保持原样，事实快照合并保留了旧断言，lineage 引用不会悬空。
    """

    catalog = bundle.workspace.recommendation_catalog
    refreshed_packets = [
        packet.model_copy(update={"fact_data_revision": facts.fact_data_revision})
        for packet in catalog.research_packets
    ]
    refreshed_catalog = catalog.model_copy(
        update={
            "generation_id": bundle.manifest.generation_id,
            "fact_data_revision": facts.fact_data_revision,
            "weather_data_revision": weather.weather_data_revision,
            "research_packets": refreshed_packets,
            "candidate_discovery_records": [
                record
                for packet in refreshed_packets
                for record in packet.candidate_discovery_records
            ],
        }
    )
    workspace = bundle.workspace.model_copy(
        update={
            "workspace_revision": bundle.workspace.workspace_revision + 1,
            "recommendation_catalog": refreshed_catalog,
        }
    )
    return workspace, weather
