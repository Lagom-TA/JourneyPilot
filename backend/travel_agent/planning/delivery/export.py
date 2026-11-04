from __future__ import annotations
from datetime import datetime, timezone
from travel_agent.runtime.blocking_work import run_blocking
from travel_agent.storage.delivery_bundle_store import BundleRevisionVector
from travel_agent.planning.run_errors import (
    DeliveryBundleMissing,
    ReportRevisionChanged,
)
from .pdf_export import render_trip_report_pdf


async def _requested_bundle(run_id: str, *, expected: BundleRevisionVector, bundle_store):
    current = await bundle_store.get_current(run_id)
    if current is None:
        raise DeliveryBundleMissing()
    if BundleRevisionVector.from_bundle(current) != expected:
        raise ReportRevisionChanged(current.manifest.bundle_id)
    return current


async def export_trip_report(
    run_id: str, *, expected: BundleRevisionVector, bundle_store
):
    current = await _requested_bundle(run_id, expected=expected, bundle_store=bundle_store)

    artifact = await run_blocking(
        "pdf_export",
        render_trip_report_pdf,
        current,
        exported_at=datetime.now(timezone.utc),
    )
    await _requested_bundle(run_id, expected=expected, bundle_store=bundle_store)
    return artifact
