from __future__ import annotations

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from pydantic import BaseModel
from pydantic import Field


class PublicBundleManifestResponse(BaseModel):
    """Public subset of Delivery Bundle manifest."""

    model_config = {"extra": "forbid"}

    contract_version: str
    run_id: str
    generation_id: str
    bundle_id: str
    workspace_revision: int
    fact_data_revision: int
    weather_data_revision: int
    created_at: str


class PublicBundleWorkspaceResponse(BaseModel):
    """Public workspace projection nested under PublicDeliveryBundleResponse."""

    model_config = {"extra": "forbid"}

    contract_version: str
    run_id: str
    generation_id: str
    workspace_revision: int
    itinerary: Dict[str, Any]
    selection_slots: List[Dict[str, Any]] = Field(default_factory=list)
    weather_proposal_decisions: List[Dict[str, Any]] = Field(default_factory=list)
    weather_adjustments: List[Dict[str, Any]] = Field(default_factory=list)


class PublicProviderEnvironmentResponse(BaseModel):
    """Whether any evidence in this plan came from a supplier's test environment."""

    model_config = {"extra": "forbid"}

    sandbox_note: Optional[str] = None


class PublicDeliveryBundleResponse(BaseModel):
    """Consumer-facing projection of the immutable Delivery Bundle.

    Top-level shape is locked. Nested itinerary/report/map bodies remain
    structured dicts projected by ``public_delivery_bundle``; OpenAPI no longer
    treats the entire Bundle as an opaque ``Dict[str, Any]``.
    """

    model_config = {"extra": "forbid"}

    manifest: PublicBundleManifestResponse
    workspace: PublicBundleWorkspaceResponse
    report_projection: Dict[str, Any]
    map_projection: Dict[str, Any]
    source_index: Dict[str, Any]
    provider_environment: PublicProviderEnvironmentResponse


class TripReportPdfExportRequest(BaseModel):
    session_id: Optional[str] = None
    bundle_id: str = Field(min_length=1)
    workspace_revision: int = Field(ge=0)
    fact_data_revision: int = Field(ge=0)
    weather_data_revision: int = Field(ge=0)
