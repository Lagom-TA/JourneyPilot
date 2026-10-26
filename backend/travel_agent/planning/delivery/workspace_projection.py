"""Workspace 变更后的交付 Bundle 构建。"""

from __future__ import annotations

from datetime import datetime
from travel_agent.planning.delivery.bundle import DeliveryBundle
from travel_agent.planning.delivery.bundle import DeliveryRevisionManifest
from travel_agent.planning.delivery.bundle import bundle_content_hashes
from travel_agent.planning.delivery.projection_builder import build_delivery_projections
from travel_agent.planning.research.evidence import FactStoreSnapshot
from travel_agent.planning.weather.models import WeatherContextSnapshot
from travel_agent.planning.workspace import TripWorkspaceV2


def _mutation_bundle(
    current: DeliveryBundle,
    workspace: TripWorkspaceV2,
    *,
    bundle_id: str,
    created_at: datetime,
    fact_snapshot: FactStoreSnapshot | None = None,
    weather_snapshot: WeatherContextSnapshot | None = None,
) -> DeliveryBundle:
    if fact_snapshot is None:
        fact_snapshot = current.fact_snapshot
    if weather_snapshot is None:
        weather_snapshot = current.weather_snapshot
    report, map_projection, source_index = build_delivery_projections(
        workspace,
        fact_snapshot,
        weather_snapshot,
        generated_at=created_at,
    )

    hashes = bundle_content_hashes(
        workspace=workspace,
        fact_snapshot=fact_snapshot,
        weather_snapshot=weather_snapshot,
        report_projection=report,
        map_projection=map_projection,
        source_index=source_index,
    )
    return DeliveryBundle(
        manifest=DeliveryRevisionManifest(
            run_id=current.manifest.run_id,
            generation_id=workspace.generation_id,
            bundle_id=bundle_id,
            workspace_revision=workspace.workspace_revision,
            fact_data_revision=fact_snapshot.fact_data_revision,
            weather_data_revision=weather_snapshot.weather_data_revision,
            contract_versions=current.manifest.contract_versions,
            content_hashes=hashes,
            created_at=created_at,
        ),
        workspace=workspace,
        fact_snapshot=fact_snapshot,
        weather_snapshot=weather_snapshot,
        report_projection=report,
        map_projection=map_projection,
        source_index=source_index,
    )
