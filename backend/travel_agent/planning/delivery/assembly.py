"""交付 Bundle 组装。"""

from __future__ import annotations

import hashlib

from travel_agent.planning.delivery.bundle import (
    DeliveryBundle,
    DeliveryRevisionManifest,
    bundle_content_hashes,
)
from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.weather.adjustments import build_weather_adjustment_proposals


def assemble_delivery_bundle(state: TravelAgentState) -> DeliveryBundle:
    workspace = state.trip_workspace_v2
    facts = state.fact_store_snapshot
    weather = state.weather_context
    report = state.report_projection
    map_projection = state.map_projection
    source_index = state.source_index_projection
    if any(
        value is None
        for value in (workspace, facts, weather, report, map_projection, source_index)
    ):
        raise ValueError("delivery finalizer requires every v2 snapshot and projection")
    assert workspace is not None
    assert facts is not None
    assert weather is not None
    assert report is not None
    assert map_projection is not None
    assert source_index is not None
    revisions = (
        workspace.workspace_revision,
        facts.fact_data_revision,
        weather.weather_data_revision,
    )
    report_revisions = (
        report.source_workspace_revision,
        report.source_fact_data_revision,
        report.source_weather_data_revision,
    )
    if (
        report.status != "ready"
        or report.document is None
        or report.generated_at is None
        or report_revisions != revisions
        or map_projection.source_workspace_revision != workspace.workspace_revision
        or source_index.source_fact_data_revision != facts.fact_data_revision
    ):
        raise ValueError(
            "delivery finalizer requires ready projections from the current bundle revisions"
        )
    weather = weather.model_copy(
        update={
            "impacts": sorted(
                state.weather_impacts.values(),
                key=lambda item: item.weather_impact_id,
            )
        }
    )
    hashes = bundle_content_hashes(
        workspace=workspace,
        fact_snapshot=facts,
        weather_snapshot=weather,
        report_projection=report,
        map_projection=map_projection,
        source_index=source_index,
    )
    identity = ":".join([workspace.run_id, *[hashes[key] for key in sorted(hashes)]])
    bundle_id = f"bundle_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"
    created_at = report.generated_at
    if created_at is None:
        raise ValueError("ready delivery report has no generated timestamp")
    bundle = DeliveryBundle(
        manifest=DeliveryRevisionManifest(
            run_id=workspace.run_id,
            generation_id=workspace.generation_id,
            bundle_id=bundle_id,
            workspace_revision=workspace.workspace_revision,
            fact_data_revision=facts.fact_data_revision,
            weather_data_revision=weather.weather_data_revision,
            contract_versions={
                "workspace": workspace.contract_version,
                "facts": facts.contract_version,
                "weather": weather.contract_version,
            },
            content_hashes=hashes,
            created_at=created_at,
        ),
        workspace=workspace,
        fact_snapshot=facts,
        weather_snapshot=weather,
        report_projection=report,
        map_projection=map_projection,
        source_index=source_index,
    )

    proposals = build_weather_adjustment_proposals(
        bundle,
        weather,
        previous_impacts={},
    )
    return bundle.model_copy(
        update={
            "weather_snapshot": weather.model_copy(
                update={"adjustment_proposals": proposals}
            )
        }
    )
