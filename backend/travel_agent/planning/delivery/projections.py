"""交付投影的数据契约。"""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import Field, model_validator

from travel_agent.planning.costs.coverage import CostCoverageSummary
from travel_agent.planning.itinerary.options import SelectionSlotType
from travel_agent.planning.references import EntityRef, EntityType
from travel_agent.planning.transport import (
    TransportEndpoint,
    TransportMode,
    TransportSegment,
)
from travel_agent.schema import StrictModel


class PublicSourceSummary(StrictModel):
    source_record_id: str = Field(min_length=1)
    source_kind: Literal["external_web", "external_tool", "rag_chunk"]
    title: str = Field(min_length=1)
    provider_name: str = Field(min_length=1)
    public_excerpt: str
    canonical_url: Optional[str] = None
    retrieved_at: datetime
    observed_at: Optional[datetime] = None
    content_hash: str = Field(min_length=1)
    rag_chunk_content: Optional[str] = None
    rag_document_locator: Optional[str] = None


class PublicSupportedValue(StrictModel):
    label: str = Field(min_length=1)
    value: Any
    unit: Optional[str] = None
    currency: Optional[str] = None


class PublicCitationProjection(StrictModel):
    citation_id: str = Field(min_length=1)
    entity_ref: EntityRef
    field_paths: List[str] = Field(min_length=1)
    fact_status: Literal["verified", "refreshing", "stale", "conflict", "missing"]
    supported_values: List[PublicSupportedValue] = Field(min_length=1)
    sources: List[PublicSourceSummary] = Field(min_length=1)
    fact_assertion_ids: List[str] = Field(min_length=1)


class ReportEntityBlock(StrictModel):
    entity_ref: EntityRef
    day_id: Optional[str] = None
    projection_role: Literal["full", "departure", "arrival", "check_in", "check_out"]
    title: str = Field(min_length=1)
    entity_kind: Literal[
        "visit",
        "dining",
        "lodging",
        "transport",
        "custom",
    ]
    summary: str = Field(min_length=1)
    details: Dict[str, Any] = Field(default_factory=dict)
    citation_ids: List[str] = Field(default_factory=list)
    weather_impact_ids: List[str] = Field(default_factory=list)
    personalization_influence_ids: List[str] = Field(default_factory=list)


class ReportDaySection(StrictModel):
    day_id: str = Field(min_length=1)
    day: int = Field(ge=1)
    date: Optional[Date] = None
    destination_id: str = Field(min_length=1)
    destination_name: str = Field(min_length=1)

    # 复制行程 Day 的主题，避免 workspace 与报告使用不同标题。
    theme: str = Field(min_length=1)
    blocks: List[ReportEntityBlock] = Field(default_factory=list)


class ReportDestination(StrictModel):
    destination_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)


class ReportSelectionOption(StrictModel):
    option_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    rank: int = Field(ge=1, le=3)
    selected: bool
    recommended: bool
    selection_reasons: List[str] = Field(default_factory=list)
    tradeoff: Optional[str] = None
    comparison_facts: List[str] = Field(default_factory=list)
    availability_status: Literal["confirmed", "needs_confirmation"]
    citation_ids: List[str] = Field(default_factory=list)


class ReportSelectionSection(StrictModel):
    selection_slot_id: str = Field(min_length=1)
    slot_type: SelectionSlotType
    context: Dict[str, Any]
    status: Literal["ready", "needs_user_decision"]
    options: List[ReportSelectionOption] = Field(min_length=1, max_length=3)


class ReportWeatherDay(StrictModel):
    destination_id: str = Field(min_length=1)
    destination_name: str = Field(min_length=1)
    date: Date
    data_kind: Literal["forecast", "seasonal_baseline", "unavailable"]

    observed_at: Optional[datetime]
    weather_data_state: Literal["current", "historical"]
    condition_label: Optional[str] = None
    high_c: Optional[float] = None
    low_c: Optional[float] = None
    precipitation_probability_pct: Optional[float] = None
    wind_speed_kph: Optional[float] = None
    citation_ids: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_timeliness(self) -> "ReportWeatherDay":
        if (self.observed_at is None) != (self.data_kind == "unavailable"):
            raise ValueError(
                "weather observation timestamp must be present exactly when the day has weather"
            )
        if self.data_kind == "unavailable" and self.weather_data_state != "current":
            raise ValueError("a day without weather cannot be in the historical state")
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError("weather observation timestamps must be timezone-aware")
        return self


class TripReportDocument(StrictModel):
    title: str = Field(min_length=1)
    overview: str = Field(min_length=1)
    destinations: List[ReportDestination] = Field(min_length=1)
    duration_days: int = Field(ge=1)
    cost_summary: CostCoverageSummary = Field(default_factory=CostCoverageSummary.empty)

    # 显式为 None 表示没有报价金额；渲染方不得编造替代值。
    cost_coverage_statement: Optional[str] = Field(min_length=1)
    days: List[ReportDaySection] = Field(min_length=1)
    selections: List[ReportSelectionSection] = Field(default_factory=list)
    weather: List[ReportWeatherDay] = Field(default_factory=list)
    highlights: List[str] = Field(default_factory=list)
    important_notes: List[str] = Field(default_factory=list)


class TripReportProjection(StrictModel):
    source_workspace_revision: int = Field(ge=0)
    source_fact_data_revision: int = Field(ge=0)
    source_weather_data_revision: int = Field(ge=0)
    status: Literal["pending", "building", "ready", "stale", "failed"]
    document: Optional[TripReportDocument] = None
    citations: List[PublicCitationProjection] = Field(default_factory=list)
    generated_at: Optional[datetime] = None
    failure_reason: Optional[str] = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "TripReportProjection":
        if self.status == "ready" and (
            self.document is None or self.generated_at is None
        ):
            raise ValueError("ready report requires a document and generated timestamp")
        if self.status == "failed" and not self.failure_reason:
            raise ValueError("failed report requires a failure reason")
        return self


class MapPlaceProjection(StrictModel):
    entity_ref: EntityRef
    name: str = Field(min_length=1)
    place_id: str = Field(min_length=1)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    citation_ids: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_coordinates(self) -> "MapPlaceProjection":
        if self.entity_ref.entity_type not in {
            EntityType.VISIT_STOP,
            EntityType.DINING_STOP,
            EntityType.LODGING_STAY,
        }:
            raise ValueError("map place projection must reference a real place entity")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError(
                "map place coordinates must be both present or both absent"
            )
        return self


class MapRouteProjection(StrictModel):
    entity_ref: EntityRef
    transport_class: Literal["long_distance", "public_transit", "flexible"]
    selected_mode: TransportMode
    route_status: Literal["pending", "ready", "unavailable"]
    from_endpoint: TransportEndpoint
    to_endpoint: TransportEndpoint
    segments: List[TransportSegment] = Field(default_factory=list)
    citation_ids: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_route_state(self) -> "MapRouteProjection":
        if self.entity_ref.entity_type != EntityType.TRANSPORT_LEG:
            raise ValueError("map route projection must reference a real transport leg")
        if self.route_status == "ready" and not self.segments:
            raise ValueError("ready map route requires segments")
        if self.route_status != "ready" and self.segments:
            raise ValueError("non-ready map route cannot expose stale segments")
        return self


class MapProjectionContent(StrictModel):
    places: List[MapPlaceProjection] = Field(default_factory=list)
    routes: List[MapRouteProjection] = Field(default_factory=list)


class MapProjection(StrictModel):
    source_workspace_revision: int = Field(ge=0)
    content: MapProjectionContent = Field(default_factory=MapProjectionContent)


class SourceIndexDocument(StrictModel):
    citations: List[PublicCitationProjection] = Field(default_factory=list)


class SourceIndexProjection(StrictModel):
    source_fact_data_revision: int = Field(ge=0)
    content: SourceIndexDocument = Field(default_factory=SourceIndexDocument)
