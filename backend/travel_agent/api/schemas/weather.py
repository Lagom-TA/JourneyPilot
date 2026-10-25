from __future__ import annotations

from typing import Optional
from pydantic import BaseModel
from pydantic import Field
from travel_agent.api.schemas.delivery import PublicDeliveryBundleResponse


class WeatherBundleRefreshRequest(BaseModel):
    session_id: Optional[str] = None
    refresh_id: str = Field(min_length=1, max_length=200)
    base_bundle_id: str = Field(min_length=1)
    base_workspace_revision: int = Field(ge=0)
    base_fact_data_revision: int = Field(ge=0)
    base_weather_data_revision: int = Field(ge=0)


class WeatherBundleRefreshResponse(BaseModel):
    refresh_id: str
    attempted: bool
    committed: bool
    used_previous_values: bool
    refusal_reason: Optional[str] = Field(
        default=None,
        description=(
            "机器可读的拒绝原因码。仅当本次刷新已尝试但被显式拒绝时出现"
            "（此时 committed=false 且 bundle 为未改变的当前 Bundle）。"
            "取值来自再录取/交付合同词表，例如 candidate_evidence_missing、"
            "weather_snapshot_inconsistent。为 null 表示没有发生拒绝。"
        ),
    )
    bundle: PublicDeliveryBundleResponse
