from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from typing import Annotated, List, Literal, Optional, Union

from pydantic import Field, model_validator

from travel_agent.planning.references import (
    EntityRef,
    SelectionSlotRef,
    TransportLegRef,
)
from travel_agent.planning.transport import TransportMode
from travel_agent.schema import StrictModel

from travel_agent.integrations.weather_contracts import WeatherTimeWindow

WEATHER_SNAPSHOT_CONTRACT_VERSION = "journeypilot.weather_context_snapshot.v2"


class WeatherSensitivity(StrictModel):
    exposure: Literal["indoor", "outdoor", "mixed"]
    rain_sensitivity: Literal["none", "low", "high"]
    heat_sensitivity: Literal["none", "low", "high"]
    cold_sensitivity: Literal["none", "low", "high"]
    wind_sensitivity: Literal["none", "low", "high"]
    requires_clear_visibility: bool




class WeatherCoverage(StrictModel):
    destination_id: str = Field(min_length=1)
    start_date: Date
    end_date: Date
    status: Literal["complete", "partial", "unavailable"]
    available_dates: List[Date] = Field(default_factory=list)
    unavailable_dates: List[Date] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_dates(self) -> "WeatherCoverage":
        if self.end_date < self.start_date:
            raise ValueError("weather coverage end date must not precede start date")
        available = set(self.available_dates)
        unavailable = set(self.unavailable_dates)
        if available & unavailable:
            raise ValueError(
                "weather coverage date cannot be both available and unavailable"
            )
        if self.status == "complete" and unavailable:
            raise ValueError(
                "complete weather coverage cannot contain unavailable dates"
            )
        if self.status == "unavailable" and available:
            raise ValueError(
                "unavailable weather coverage cannot contain available dates"
            )
        return self


class WeatherDayContext(StrictModel):
    destination_id: str = Field(min_length=1)
    date: Date
    timezone: Optional[str] = Field(default=None, min_length=1)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    data_kind: Literal["forecast", "seasonal_baseline", "unavailable"]
    condition_code: Optional[int] = None
    condition_label: Optional[str] = None
    high_c: Optional[float] = None
    low_c: Optional[float] = None
    apparent_high_c: Optional[float] = None
    precipitation_probability_pct: Optional[float] = Field(default=None, ge=0, le=100)
    precipitation_mm: Optional[float] = Field(default=None, ge=0)
    wind_speed_kph: Optional[float] = Field(default=None, ge=0)
    wind_gust_kph: Optional[float] = Field(default=None, ge=0)
    hourly_windows: List[WeatherTimeWindow] = Field(default_factory=list)
    alert_ids: List[str] = Field(default_factory=list)
    fact_assertion_ids: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unavailable(self) -> "WeatherDayContext":
        factual_values = (
            self.condition_code,
            self.condition_label,
            self.high_c,
            self.low_c,
            self.apparent_high_c,
            self.precipitation_probability_pct,
            self.precipitation_mm,
            self.wind_speed_kph,
            self.wind_gust_kph,
        )
        if self.data_kind == "unavailable" and any(
            value is not None for value in factual_values
        ):
            raise ValueError("unavailable weather must not contain fabricated facts")
        if self.data_kind == "seasonal_baseline" and (
            self.condition_code is not None
            or self.condition_label is not None
            or self.apparent_high_c is not None
            or self.precipitation_probability_pct is not None
            or self.hourly_windows
        ):
            raise ValueError("seasonal baseline cannot masquerade as a daily forecast")
        if self.data_kind != "unavailable" and self.timezone is None:
            raise ValueError("available weather requires a resolved timezone")
        return self


class WeatherImpact(StrictModel):
    weather_impact_id: str = Field(min_length=1)
    date: Date
    target_ref: Union[EntityRef, SelectionSlotRef, TransportLegRef]
    condition_type: Literal[
        "rain", "heat", "cold", "wind", "thunderstorm", "snow", "visibility"
    ]
    severity: Literal["low", "medium", "high"]
    action: Literal[
        "keep",
        "move_time",
        "rerank",
        "replace",
        "change_transport",
        "add_buffer",
        "require_plan_b",
    ]
    fact_assertion_ids: List[str] = Field(min_length=1)
    affected_constraint_ids: List[str] = Field(default_factory=list)
    data_kind: Literal["forecast", "seasonal_baseline"]
    trigger_code: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_action(self) -> "WeatherImpact":
        if self.data_kind == "seasonal_baseline" and self.action in {
            "move_time",
            "replace",
            "change_transport",
            "add_buffer",
            "require_plan_b",
        }:
            raise ValueError(
                "seasonal baseline cannot drive a day-specific itinerary change"
            )
        if self.severity == "high" and self.action not in {
            "replace",
            "change_transport",
        }:
            raise ValueError(
                "high weather impact must remove an unsafe candidate or transport mode"
            )
        return self


class WeatherRescheduleOperation(StrictModel):
    type: Literal["reschedule_item"] = "reschedule_item"
    item_id: str = Field(min_length=1)
    expected_planned_start: Optional[datetime] = None
    expected_planned_end: Optional[datetime] = None
    planned_start: datetime
    planned_end: datetime

    @model_validator(mode="after")
    def validate_schedule(self) -> "WeatherRescheduleOperation":
        if self.planned_end <= self.planned_start:
            raise ValueError("weather reschedule must end after it starts")
        if (
            self.expected_planned_start == self.planned_start
            and self.expected_planned_end == self.planned_end
        ):
            raise ValueError("weather reschedule must change the current schedule")
        return self


class WeatherSelectionOperation(StrictModel):
    type: Literal["select_option"] = "select_option"
    selection_slot_id: str = Field(min_length=1)
    expected_option_id: Optional[str] = Field(default=None, min_length=1)
    option_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_option_change(self) -> "WeatherSelectionOperation":
        if self.expected_option_id == self.option_id:
            raise ValueError("weather selection must choose another option")
        return self


class WeatherVisitReplacementOperation(StrictModel):
    type: Literal["replace_visit_candidate"] = "replace_visit_candidate"
    item_id: str = Field(min_length=1)
    expected_candidate_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_candidate_change(self) -> "WeatherVisitReplacementOperation":
        if self.expected_candidate_id == self.candidate_id:
            raise ValueError("weather visit replacement must use another candidate")
        return self


class WeatherTransportModeOperation(StrictModel):
    type: Literal["set_transport_mode"] = "set_transport_mode"
    transport_leg_id: str = Field(min_length=1)
    expected_mode: TransportMode
    selected_mode: TransportMode

    @model_validator(mode="after")
    def validate_mode_change(self) -> "WeatherTransportModeOperation":
        if self.expected_mode == self.selected_mode:
            raise ValueError("weather transport adjustment must change mode")
        return self


class WeatherBufferOperation(StrictModel):
    type: Literal["add_buffer"] = "add_buffer"
    target_entity_id: str = Field(min_length=1)
    day_id: str = Field(min_length=1)
    block_id: str = Field(min_length=1)
    duration_minutes: int = Field(ge=5, le=180)


WeatherAdjustmentOperation = Annotated[
    Union[
        WeatherRescheduleOperation,
        WeatherSelectionOperation,
        WeatherVisitReplacementOperation,
        WeatherTransportModeOperation,
        WeatherBufferOperation,
    ],
    Field(discriminator="type"),
]


class WeatherAdjustmentProposal(StrictModel):
    proposal_id: str = Field(min_length=1)
    date: Date
    base_workspace_revision: int = Field(ge=0)
    base_weather_data_revision: int = Field(ge=1)
    severity: Literal["medium", "high"]
    summary: str = Field(min_length=1)
    weather_impact_ids: List[str] = Field(min_length=1)
    fact_assertion_ids: List[str] = Field(min_length=1)
    operations: List[WeatherAdjustmentOperation] = Field(min_length=1)
    cost_delta_cny: Optional[float] = None
    time_delta_minutes: Optional[int] = None

    @model_validator(mode="after")
    def validate_unique_refs(self) -> "WeatherAdjustmentProposal":
        if len(self.weather_impact_ids) != len(set(self.weather_impact_ids)):
            raise ValueError("weather proposal impact ids must be unique")
        if len(self.fact_assertion_ids) != len(set(self.fact_assertion_ids)):
            raise ValueError("weather proposal fact ids must be unique")
        operation_keys = [item.model_dump_json() for item in self.operations]
        if len(operation_keys) != len(set(operation_keys)):
            raise ValueError("weather proposal operations must be unique")
        return self


class WeatherContextSnapshot(StrictModel):
    contract_version: Literal[WEATHER_SNAPSHOT_CONTRACT_VERSION] = (
        WEATHER_SNAPSHOT_CONTRACT_VERSION
    )
    weather_data_revision: int = Field(ge=0)
    trip_start_date: Date
    trip_end_date: Date
    days: List[WeatherDayContext]
    coverage: List[WeatherCoverage] = Field(default_factory=list)
    impacts: List[WeatherImpact] = Field(default_factory=list)
    adjustment_proposals: List[WeatherAdjustmentProposal] = Field(default_factory=list)
    retrieved_at: datetime

    @model_validator(mode="after")
    def validate_coverage(self) -> "WeatherContextSnapshot":
        if self.trip_end_date < self.trip_start_date:
            raise ValueError("weather trip end date must not precede start date")
        day_keys = [(day.destination_id, day.date) for day in self.days]
        if len(day_keys) != len(set(day_keys)):
            raise ValueError("weather destination/date pairs must be unique")
        if any(
            day.date < self.trip_start_date or day.date > self.trip_end_date
            for day in self.days
        ):
            raise ValueError("weather day falls outside trip date range")
        coverage_ids = [item.destination_id for item in self.coverage]
        if len(coverage_ids) != len(set(coverage_ids)):
            raise ValueError("weather coverage destination ids must be unique")
        for item in self.coverage:
            expected = {
                day.date
                for day in self.days
                if day.destination_id == item.destination_id
            }
            declared = set(item.available_dates) | set(item.unavailable_dates)
            if expected != declared:
                raise ValueError("weather coverage dates must match destination days")
        impact_ids = [item.weather_impact_id for item in self.impacts]
        if len(impact_ids) != len(set(impact_ids)):
            raise ValueError("weather impact ids must be unique")
        proposal_ids = [item.proposal_id for item in self.adjustment_proposals]
        if len(proposal_ids) != len(set(proposal_ids)):
            raise ValueError("weather adjustment proposal ids must be unique")
        impact_index = {item.weather_impact_id: item for item in self.impacts}
        for proposal in self.adjustment_proposals:
            if proposal.base_weather_data_revision != self.weather_data_revision:
                raise ValueError(
                    "weather proposal must bind the containing weather revision"
                )
            if not set(proposal.weather_impact_ids) <= impact_index.keys():
                raise ValueError("weather proposal references a missing impact")
            if any(
                impact_index[item].date != proposal.date
                for item in proposal.weather_impact_ids
            ):
                raise ValueError(
                    "weather proposal may only combine impacts from one day"
                )
            expected_severity = (
                "high"
                if any(
                    impact_index[item].severity == "high"
                    for item in proposal.weather_impact_ids
                )
                else "medium"
            )
            if proposal.severity != expected_severity:
                raise ValueError("weather proposal severity does not match its impacts")
        return self


class WeatherProposalDecision(StrictModel):
    proposal_id: str = Field(min_length=1)
    decision: Literal["applied", "dismissed"]
