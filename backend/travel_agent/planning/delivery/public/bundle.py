"""Planning delivery public bundle."""

from __future__ import annotations

from travel_agent.planning.delivery.bundle import DeliveryBundle
from travel_agent.planning.delivery.coverage_presentation import (
    coverage_disclosure_notes,
)
from travel_agent.planning.delivery.evidence_basis import EvidenceBasisView
from travel_agent.planning.delivery.provider_environment import ProviderEnvironmentView
from travel_agent.planning.delivery.public.itinerary import _timestamp
from travel_agent.planning.delivery.public.report import _public_map
from travel_agent.planning.delivery.public.report import _public_report
from travel_agent.planning.delivery.public.report import _public_source_index
from travel_agent.planning.delivery.public.workspace import _public_workspace
from typing import Any
from typing import Dict
from typing import Mapping


_PUBLIC_MANIFEST_KEYS = (
    "contract_version",
    "run_id",
    "generation_id",
    "bundle_id",
    "workspace_revision",
    "fact_data_revision",
    "weather_data_revision",
    "created_at",
)


def public_manifest(bundle: DeliveryBundle) -> Dict[str, Any]:
    manifest = bundle.manifest
    return {
        "contract_version": manifest.contract_version,
        "run_id": manifest.run_id,
        "generation_id": manifest.generation_id,
        "bundle_id": manifest.bundle_id,
        "workspace_revision": manifest.workspace_revision,
        "fact_data_revision": manifest.fact_data_revision,
        "weather_data_revision": manifest.weather_data_revision,
        "created_at": _timestamp(manifest.created_at),
    }


def public_event_manifest(manifest: Any) -> Dict[str, Any]:
    """Coerce a persisted manifest payload to the public manifest subset.

    The input is a durable event payload rather than a typed model, so the
    projection reads the named keys it knows and ignores everything else.
    """

    if not isinstance(manifest, Mapping):
        return {}
    return {key: manifest[key] for key in _PUBLIC_MANIFEST_KEYS if key in manifest}


def public_delivery_bundle(bundle: DeliveryBundle) -> Dict[str, Any]:
    """Return the only DeliveryBundle shape valid on normal product surfaces.

    The persisted ``EntityLineage`` never crosses this boundary, so without a
    derived field a traveller cannot tell an entry backed by an admitted research
    candidate from one the Itinerary Planner authored against public knowledge —
    the two render identically while only one can expand its sources.
    ``evidence_basis`` states that difference in product language and is derived
    once here, so the workspace card and the formal report can never disagree
    about the same entity.
    """

    view = EvidenceBasisView.from_itinerary(bundle.workspace.itinerary)
    return {
        "manifest": public_manifest(bundle),
        "workspace": _public_workspace(bundle.workspace, bundle, view),
        "report_projection": _public_report(bundle.report_projection, view),
        "map_projection": _public_map(bundle.map_projection),
        "source_index": _public_source_index(bundle.source_index),
        "coverage_disclosure": {
            "notes": coverage_disclosure_notes(bundle.coverage_disclosure)
        },
        "provider_environment": {
            "sandbox_note": ProviderEnvironmentView.from_bundle(bundle).sandbox_note
        },
    }
