"""Planning delivery weather refresh."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from pydantic import ValidationError
from travel_agent.integrations.weather import WeatherProviderRequest
from travel_agent.planning.delivery.bundle import DeliveryBundle
from travel_agent.planning.delivery.bundle import DeliveryRevisionManifest
from travel_agent.planning.delivery.bundle import bundle_content_hashes
from travel_agent.planning.delivery.projection_builder import build_delivery_projections
from travel_agent.planning.delivery.weather_refresh_contracts import (
    WEATHER_SNAPSHOT_INCONSISTENT,
)
from travel_agent.planning.delivery.weather_refresh_contracts import (
    WeatherBundleRefreshResult,
)
from travel_agent.planning.delivery.weather_refresh_contracts import (
    WeatherRefreshRefused,
)
from travel_agent.planning.weather.adjustments import build_weather_adjustment_proposals
from travel_agent.planning.weather.context_builder import WeatherContextBuildResult
from travel_agent.planning.weather.context_builder import WeatherContextBuilder
from travel_agent.planning.weather.models import WeatherDayContext
from travel_agent.planning.weather.refresh import _carry_over_frozen_impacts
from travel_agent.planning.weather.refresh import _fact_snapshot
from travel_agent.planning.weather.refresh import _rebind_catalog_for_snapshot
from travel_agent.planning.weather.refresh import _weather_snapshot
from travel_agent.planning.weather.refresh import expired_weather_destination_ids
from travel_agent.planning.weather.refresh import logger
from travel_agent.storage.delivery_bundle_store import BundleCommitKind
from travel_agent.storage.delivery_bundle_store import BundleIdempotencyMismatch
from travel_agent.storage.delivery_bundle_store import BundleRevisionConflict
from travel_agent.storage.delivery_bundle_store import BundleRevisionVector
from travel_agent.storage.delivery_bundle_store import DeliveryBundleStore
from typing import Callable
from uuid import uuid4
import hashlib
import json


Clock = Callable[[], datetime]


IdFactory = Callable[[], str]


def _build_refreshed_bundle(
    bundle: DeliveryBundle,
    result: WeatherContextBuildResult,
    *,
    now: datetime,
    id_factory: IdFactory,
) -> tuple[DeliveryBundle, bool]:
    """Recompute one whole candidate Bundle revision from a new forecast.

    Every step here is pure: it either yields a fully valid next Bundle or
    refuses.  Re-admission refuses through ``WeatherRefreshRefused``; the
    Delivery Bundle contract refuses through ``ValidationError`` when the
    recomputed weather view no longer covers frozen canonical lineage.  The
    caller turns both into a typed refusal instead of an unhandled error.
    """

    facts = _fact_snapshot(bundle, result)
    weather, used_previous, retained_days = _weather_snapshot(bundle, result)
    workspace, weather = _rebind_catalog_for_snapshot(
        bundle,
        facts=facts,
        weather=weather,
        now=now,
    )

    weather, carried_impact_ids, carried_days = _carry_over_frozen_impacts(
        bundle, weather
    )
    staging_for_proposals = DeliveryBundle.model_construct(
        manifest=DeliveryRevisionManifest(
            run_id=bundle.manifest.run_id,
            generation_id=bundle.manifest.generation_id,
            bundle_id=bundle.manifest.bundle_id,
            workspace_revision=workspace.workspace_revision,
            fact_data_revision=facts.fact_data_revision,
            weather_data_revision=weather.weather_data_revision,
            contract_versions=bundle.manifest.contract_versions,
            content_hashes=bundle.manifest.content_hashes,
            created_at=now,
        ),
        workspace=workspace,
        fact_snapshot=facts,
        weather_snapshot=bundle.weather_snapshot,
        report_projection=bundle.report_projection,
        map_projection=bundle.map_projection,
        source_index=bundle.source_index,
    )
    weather = weather.model_copy(
        update={
            "adjustment_proposals": build_weather_adjustment_proposals(
                staging_for_proposals,
                weather,
                carried_over_impact_ids=carried_impact_ids,
            )
        }
    )
    report, map_projection, source_index = build_delivery_projections(
        workspace,
        facts,
        weather,
        generated_at=now,
        historical_weather_days=retained_days | carried_days,
    )

    coverage_disclosure = bundle.coverage_disclosure
    hashes = bundle_content_hashes(
        workspace=workspace,
        fact_snapshot=facts,
        weather_snapshot=weather,
        report_projection=report,
        map_projection=map_projection,
        source_index=source_index,
        coverage_disclosure=coverage_disclosure,
    )
    generated_id = id_factory()
    bundle_id = (
        generated_id
        or f"bundle_{hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()[:24]}"
    )
    refreshed = DeliveryBundle(
        manifest=DeliveryRevisionManifest(
            run_id=bundle.manifest.run_id,
            generation_id=bundle.manifest.generation_id,
            bundle_id=bundle_id,
            workspace_revision=workspace.workspace_revision,
            fact_data_revision=facts.fact_data_revision,
            weather_data_revision=weather.weather_data_revision,
            contract_versions=bundle.manifest.contract_versions,
            content_hashes=hashes,
            created_at=now,
        ),
        workspace=workspace,
        fact_snapshot=facts,
        weather_snapshot=weather,
        report_projection=report,
        map_projection=map_projection,
        source_index=source_index,
        coverage_disclosure=coverage_disclosure,
    )
    return refreshed, used_previous


class WeatherBundleRefreshService:
    def __init__(
        self,
        store: DeliveryBundleStore,
        builder: WeatherContextBuilder,
        *,
        clock: Clock = lambda: datetime.now(timezone.utc),
        id_factory: IdFactory = lambda: f"bundle_{uuid4().hex}",
    ) -> None:
        self._store = store
        self._builder = builder
        self._clock = clock
        self._id_factory = id_factory

    async def refresh_if_needed(
        self,
        *,
        run_id: str,
        expected: BundleRevisionVector,
        idempotency_key: str,
        operation: str = "weather_refresh_before_export",
    ) -> WeatherBundleRefreshResult:
        refresh_request = {
            "operation": operation,
            "base_bundle_id": expected.bundle_id,
            "base_workspace_revision": expected.workspace_revision,
            "base_fact_data_revision": expected.fact_data_revision,
            "base_weather_data_revision": expected.weather_data_revision,
        }
        replay = await self._store.get_commit(run_id, idempotency_key)
        if replay is not None:
            if replay.metadata.get("weather_refresh_request") != refresh_request:
                raise BundleIdempotencyMismatch(
                    "idempotency key was used for another weather refresh"
                )
            return WeatherBundleRefreshResult(
                replay.result.bundle,
                bool(replay.metadata["attempted"]),
                bool(replay.metadata["committed"]),
                bool(replay.metadata["used_previous_values"]),
            )
        current = await self._store.get_current(run_id)
        if current is None or BundleRevisionVector.from_bundle(current) != expected:
            raise BundleRevisionConflict(
                BundleRevisionVector.from_bundle(current)
                if current is not None
                else None
            )
        bundle = current
        now = self._clock()
        destination_ids = expired_weather_destination_ids(bundle, now=now)
        if not destination_ids:
            receipt = await self._store.record_noop_receipt(
                run_id=run_id,
                idempotency_key=idempotency_key,
                expected=expected,
                kind=BundleCommitKind.WEATHER_REFRESH_RECEIPT,
                idempotency_request=refresh_request,
                metadata={
                    "operation": operation,
                    "weather_refresh_request": refresh_request,
                    "refresh_outcome": "no_refresh_needed",
                    "attempted": False,
                    "committed": False,
                    "used_previous_values": False,
                },
            )
            return WeatherBundleRefreshResult(receipt.bundle, False, False, False)
        grouped: dict[str, list[WeatherDayContext]] = {}
        for day in bundle.weather_snapshot.days:
            if day.destination_id in destination_ids:
                grouped.setdefault(day.destination_id, []).append(day)
        requests = [
            WeatherProviderRequest(
                destination_id=destination_id,
                destination_name=destination_id,
                latitude=items[0].latitude,
                longitude=items[0].longitude,
                timezone=items[0].timezone,
                start_date=min(item.date for item in items),
                end_date=max(item.date for item in items),
            )
            for destination_id, items in sorted(grouped.items())
        ]
        result = await self._builder.build(
            requests=requests,
            weather_data_revision=bundle.manifest.weather_data_revision + 1,
            trip_start_date=bundle.weather_snapshot.trip_start_date,
            trip_end_date=bundle.weather_snapshot.trip_end_date,
        )
        if not any(
            day.data_kind != "unavailable" for day in result.weather_snapshot.days
        ):
            latest = await self._store.get_current(run_id)
            if latest is None or BundleRevisionVector.from_bundle(latest) != expected:
                raise BundleRevisionConflict(
                    BundleRevisionVector.from_bundle(latest)
                    if latest is not None
                    else None
                )
            return WeatherBundleRefreshResult(bundle, True, False, True)

        try:
            refreshed, used_previous = _build_refreshed_bundle(
                bundle,
                result,
                now=now,
                id_factory=self._id_factory,
            )
        except (WeatherRefreshRefused, ValidationError) as exc:
            reason = (
                exc.code
                if isinstance(exc, WeatherRefreshRefused)
                else WEATHER_SNAPSHOT_INCONSISTENT
            )
            logger.warning(
                "weather refresh refused run_id=%s bundle_id=%s reason=%s: %s",
                run_id,
                bundle.manifest.bundle_id,
                reason,
                exc,
            )
            latest = await self._store.get_current(run_id)
            if latest is None or BundleRevisionVector.from_bundle(latest) != expected:
                raise BundleRevisionConflict(
                    BundleRevisionVector.from_bundle(latest)
                    if latest is not None
                    else None
                ) from exc
            return WeatherBundleRefreshResult(bundle, True, False, False, reason)
        commit = await self._store.commit(
            bundle=refreshed,
            kind=BundleCommitKind.WEATHER_FACT_REFRESH,
            idempotency_key=idempotency_key,
            expected=expected,
            metadata={
                "operation": operation,
                "weather_refresh_request": refresh_request,
                "refresh_outcome": "committed",
                "attempted": True,
                "committed": True,
                "used_previous_values": used_previous,
            },
            idempotency_request=refresh_request,
        )
        if commit.idempotent_replay:
            stored = await self._store.get_commit(run_id, idempotency_key)
            if (
                stored is None
                or stored.metadata.get("weather_refresh_request") != refresh_request
            ):
                raise BundleIdempotencyMismatch(
                    "idempotency key was used for another weather refresh"
                )
            return WeatherBundleRefreshResult(
                stored.result.bundle,
                bool(stored.metadata["attempted"]),
                bool(stored.metadata["committed"]),
                bool(stored.metadata["used_previous_values"]),
            )
        return WeatherBundleRefreshResult(
            commit.bundle,
            True,
            True,
            used_previous,
        )
