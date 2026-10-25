"""Planning delivery workspace projection."""

from __future__ import annotations

from datetime import datetime
from travel_agent.planning.delivery.bundle import DeliveryBundle
from travel_agent.planning.delivery.bundle import DeliveryRevisionManifest
from travel_agent.planning.delivery.bundle import bundle_content_hashes
from travel_agent.planning.delivery.projection_builder import build_delivery_projections
from travel_agent.planning.research.evidence import FactStoreSnapshot
from travel_agent.planning.weather.adjustments import build_weather_adjustment_proposals
from travel_agent.planning.weather.models import WeatherContextSnapshot
from travel_agent.planning.weather.models import WeatherImpact
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


def _weather_with_readmission_impacts(
    current: DeliveryBundle,
    impacts: tuple[WeatherImpact, ...],
    *,
    workspace: TripWorkspaceV2 | None = None,
) -> WeatherContextSnapshot:
    """Persist newly evaluated Candidate impacts as an immutable weather revision.

    Candidate weather lineage must point into the same Bundle's weather
    snapshot.  When re-admission produces new impact records, advancing the
    weather revision is required: revision snapshots may never be replaced in
    place just to add a Candidate-specific derived impact.
    """

    merged = {item.weather_impact_id: item for item in current.weather_snapshot.impacts}
    for impact in impacts:
        merged[impact.weather_impact_id] = impact
    if len(merged) == len(current.weather_snapshot.impacts) and all(
        merged[item.weather_impact_id] == item
        for item in current.weather_snapshot.impacts
    ):
        return current.weather_snapshot
    merged_impacts = sorted(merged.values(), key=lambda item: item.weather_impact_id)

    provisional = current.weather_snapshot.model_copy(
        update={
            "weather_data_revision": current.manifest.weather_data_revision + 1,
            "impacts": merged_impacts,
            "adjustment_proposals": [],
        }
    )
    proposal_bundle = DeliveryBundle.model_construct(
        manifest=current.manifest,
        workspace=workspace or current.workspace,
        fact_snapshot=current.fact_snapshot,
        weather_snapshot=current.weather_snapshot,
        report_projection=current.report_projection,
        map_projection=current.map_projection,
        source_index=current.source_index,
    )
    return provisional.model_copy(
        update={
            "adjustment_proposals": build_weather_adjustment_proposals(
                proposal_bundle, provisional
            )
        }
    )


def _canonical_candidate_scopes(
    workspace: TripWorkspaceV2,
) -> dict[tuple[str, str], tuple[str, str | None]]:
    """Index every canonical Candidate materialization by stable entity identity."""

    itinerary = workspace.itinerary
    entities = (
        *(("visit", item.item_id, item) for item in itinerary.visit_stops),
        *(("dining", item.item_id, item) for item in itinerary.dining_stops),
        *(("lodging", item.stay_id, item) for item in itinerary.lodging_stays),
        *(
            ("transport", item.transport_leg_id, item)
            for item in itinerary.transport_legs
        ),
    )
    return {
        (kind, entity_id): (item.lineage.candidate_id, item.lineage.selection_slot_id)
        for kind, entity_id, item in entities
        if item.lineage.lineage_kind == "candidate_entity"
    }


def _new_candidate_materializations(
    before: TripWorkspaceV2,
    after: TripWorkspaceV2,
) -> tuple[tuple[str, str | None], ...]:
    """Find only Candidate lineages newly written by a pure reducer application."""

    previous = _canonical_candidate_scopes(before)
    current = _canonical_candidate_scopes(after)
    return tuple(
        dict.fromkeys(
            value for key, value in current.items() if previous.get(key) != value
        )
    )
