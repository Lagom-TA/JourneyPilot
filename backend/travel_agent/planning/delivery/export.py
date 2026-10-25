from __future__ import annotations
from datetime import datetime, timezone
from travel_agent.runtime.blocking_work import run_blocking
from travel_agent.storage.delivery_bundle_store import BundleRevisionVector
from travel_agent.planning.run_errors import (
    DeliveryBundleMissing,
    ReportRevisionChanged,
)
from .pdf_export import render_trip_report_pdf


async def export_trip_report(
    run_id: str, *, expected: BundleRevisionVector, bundle_store
):
    current = await bundle_store.get_current(run_id)
    if current is None:
        raise DeliveryBundleMissing()
    manifest = current.manifest
    requested = (
        expected.bundle_id,
        expected.workspace_revision,
        expected.fact_data_revision,
        expected.weather_data_revision,
    )
    actual = (
        manifest.bundle_id,
        manifest.workspace_revision,
        manifest.fact_data_revision,
        manifest.weather_data_revision,
    )
    if requested != actual:
        raise ReportRevisionChanged(manifest.bundle_id)

    artifact = await run_blocking(
        "pdf_export",
        render_trip_report_pdf,
        current,
        exported_at=datetime.now(timezone.utc),
    )
    return artifact
