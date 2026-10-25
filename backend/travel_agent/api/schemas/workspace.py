from __future__ import annotations

from typing import List
from typing import Literal
from typing import Optional
from pydantic import BaseModel
from pydantic import Field
from travel_agent.planning.itinerary.mutations.contracts import WorkspaceV2Mutation
from travel_agent.api.schemas.delivery import PublicDeliveryBundleResponse


class WorkspaceV2MutationRequest(BaseModel):
    session_id: Optional[str] = None
    mutation_id: str = Field(min_length=1, max_length=200)
    base_bundle_id: str = Field(min_length=1)
    base_workspace_revision: int = Field(ge=0)
    base_fact_data_revision: int = Field(ge=0)
    base_weather_data_revision: int = Field(ge=0)
    operation: WorkspaceV2Mutation


class WorkspaceV2MutationImpactResponse(BaseModel):
    kind: Literal["total_cost"]
    delta_cny: float
    summary: str


class WorkspaceV2MutationPreviewResponse(BaseModel):
    mutation_id: str
    allowed: bool = True
    changed: bool
    requires_confirmation: bool
    impacts: List[WorkspaceV2MutationImpactResponse] = Field(default_factory=list)


class WorkspaceV2MutationResponse(BaseModel):
    mutation_id: str
    changed: bool
    idempotent_replay: bool
    bundle: PublicDeliveryBundleResponse


class WorkspaceV2UndoHeadResponse(BaseModel):
    available: bool
    mutation_id: Optional[str] = None
    label: Optional[str] = None


class WorkspaceV2UndoRequest(BaseModel):
    session_id: Optional[str] = None
    undo_id: str = Field(min_length=1, max_length=200)
    undo_of_mutation_id: str = Field(min_length=1, max_length=200)
    base_bundle_id: str = Field(min_length=1)
    base_workspace_revision: int = Field(ge=0)
    base_fact_data_revision: int = Field(ge=0)
    base_weather_data_revision: int = Field(ge=0)


class WorkspaceV2UndoResponse(BaseModel):
    undo_id: str
    idempotent_replay: bool
    bundle: PublicDeliveryBundleResponse
