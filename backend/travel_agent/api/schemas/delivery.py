from __future__ import annotations

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from pydantic import BaseModel
from pydantic import Field


class PublicBundleManifestResponse(BaseModel):
    """Delivery Bundle manifest 的公开子集。"""

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
    """嵌套在 PublicDeliveryBundleResponse 中的公开工作区投影。"""

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
    """本方案中是否有证据来自供应商测试环境。"""

    model_config = {"extra": "forbid"}

    sandbox_note: Optional[str] = None


class PublicDeliveryBundleResponse(BaseModel):
    """不可变 Delivery Bundle 的消费端投影。

    顶层结构固定；内层的行程、报告、地图仍是由 ``public_delivery_bundle``
    投影出的结构化 dict，OpenAPI 中不再把整个 Bundle 表示为不透明的 dict。
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
