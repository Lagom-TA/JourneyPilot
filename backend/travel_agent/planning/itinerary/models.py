from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from typing import Dict, Iterable, List, Literal, Optional

from pydantic import Field, model_validator

from travel_agent.planning.delivery.requirement_contracts import EntityIntentExplanation
from travel_agent.planning.transport_semantics import count_service_transfers
from travel_agent.planning.costs.coverage import (
    CostCoverageSummary,
    build_cost_coverage_summary,
    itinerary_price_components,
)
from travel_agent.planning.references import EntityLineage, EntityType
from travel_agent.planning.transport import (
    TransportEndpoint,
    TransportMode,
    TransportModePreference,
    TransportSegment,
)
from travel_agent.schema import StrictModel


class TransportLeg(StrictModel):
    type: Literal["transport_leg"] = "transport_leg"
    transport_leg_id: str = Field(min_length=1)
    transport_class: Literal["long_distance", "public_transit", "flexible"]
    selected_mode: TransportMode
    from_endpoint: TransportEndpoint
    to_endpoint: TransportEndpoint
    departure_at: Optional[datetime] = None
    arrival_at: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(default=None, ge=0)
    distance_meters: Optional[int] = Field(default=None, ge=0)
    total_cost_cny: Optional[float] = Field(default=None, ge=0)
    transfer_count: int = Field(ge=0)
    segments: List[TransportSegment] = Field(default_factory=list)
    booking_status: Literal[
        "not_required", "recommended", "required", "booked", "unknown"
    ]
    route_status: Literal["pending", "ready", "unavailable"]
    mode_preference: TransportModePreference = Field(
        default_factory=TransportModePreference
    )
    intent_explanations: List[EntityIntentExplanation] = Field(default_factory=list)
    lineage: EntityLineage

    @model_validator(mode="after")
    def validate_route(self) -> "TransportLeg":
        # 换乘数按实际班次变化统计，不按分段边界统计。
        object.__setattr__(
            self, "transfer_count", count_service_transfers(self.segments)
        )
        if self.route_status == "ready" and not self.segments:
            raise ValueError("ready transport leg requires at least one segment")
        if self.segments:
            first = self.segments[0]
            last = self.segments[-1]
            if (
                first.from_endpoint != self.from_endpoint
                or last.to_endpoint != self.to_endpoint
            ):
                raise ValueError("transport segment endpoints must match leg endpoints")
        return self


class ScheduledStopBase(StrictModel):
    item_id: str = Field(min_length=1)
    day_id: str = Field(min_length=1)
    place_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    address: Optional[str] = None

    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    planned_start: Optional[datetime] = None
    planned_end: Optional[datetime] = None
    duration_minutes: int = Field(ge=1)
    estimated_cost_cny: Optional[float] = Field(default=None, ge=0)
    selection_reason: str = Field(min_length=1)
    intent_explanations: List[EntityIntentExplanation] = Field(default_factory=list)
    lineage: EntityLineage


class VisitStop(ScheduledStopBase):
    type: Literal["visit_stop"] = "visit_stop"
    visit_type: Literal[
        "attraction", "experience", "culture", "shopping", "nature", "other"
    ]
    opening_window: Optional[str] = None
    reservation_required: Optional[bool] = None
    visit_highlights: List[str] = Field(default_factory=list)


class DiningStop(ScheduledStopBase):
    type: Literal["dining_stop"] = "dining_stop"
    meal_type: Literal["breakfast", "lunch", "dinner", "snack", "other"]
    cuisine_types: List[str] = Field(default_factory=list)
    average_spend_cny: Optional[float] = Field(default=None, ge=0)
    recommended_dishes: List[str] = Field(default_factory=list)
    reservation_required: Optional[bool] = None
    opening_window: Optional[str] = None
    dining_reminders: List[str] = Field(default_factory=list)


class LodgingStay(StrictModel):
    type: Literal["lodging_stay"] = "lodging_stay"
    stay_id: str = Field(min_length=1)
    place_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    check_in_date: Date
    check_out_date: Date
    check_in_time: Optional[str] = None
    check_out_time: Optional[str] = None
    nights: int = Field(ge=1)
    room_type: Optional[str] = None
    nightly_price_cny: Optional[float] = Field(default=None, ge=0)
    total_price_cny: Optional[float] = Field(default=None, ge=0)

    # 参考估价只是规划输入，不是已确认的当前报价。
    price_kind: Literal["reference_estimate", "live_quote"] = "reference_estimate"
    availability_status: Literal["confirmed", "needs_confirmation", "unavailable"] = (
        "needs_confirmation"
    )
    address: str = Field(min_length=1)
    selection_reason: str = Field(min_length=1)
    intent_explanations: List[EntityIntentExplanation] = Field(default_factory=list)
    lineage: EntityLineage

    @model_validator(mode="after")
    def validate_nights(self) -> "LodgingStay":
        expected = (self.check_out_date - self.check_in_date).days
        if expected < 1 or self.nights != expected:
            raise ValueError("nights must equal check-out date minus check-in date")
        if (
            self.price_kind == "reference_estimate"
            and self.availability_status == "confirmed"
        ):
            raise ValueError(
                "reference_estimate lodging cannot be availability confirmed; "
                "use needs_confirmation or a live_quote"
            )
        return self


class CustomBlock(StrictModel):
    type: Literal["custom_block"] = "custom_block"
    item_id: str = Field(min_length=1)
    day_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    note: Optional[str] = None
    planned_start: Optional[datetime] = None
    planned_end: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(default=None, ge=1)


class TimelineEntryRef(StrictModel):
    entry_id: str = Field(min_length=1)
    entity_type: EntityType
    entity_id: str = Field(min_length=1)
    projection_role: Literal[
        "full", "departure", "arrival", "check_in", "check_out"
    ] = "full"


TransportProjectionShape = Literal[
    "single_full",
    "cross_night_split",
    "cross_night_boundary_full",
    "outside_itinerary",
]


def classify_transport_projection_shape(
    *,
    transport_class: str,
    departure_at: Optional[datetime],
    arrival_at: Optional[datetime],
    itinerary_dates: Iterable[Date],
) -> TransportProjectionShape:
    # 跨日期边界的班次不会额外生成行程日。
    if (
        transport_class != "long_distance"
        or departure_at is None
        or arrival_at is None
        or departure_at.date() == arrival_at.date()
    ):
        return "single_full"
    dates = set(itinerary_dates)
    matched_dates = {departure_at.date(), arrival_at.date()} & dates
    if len(matched_dates) == 2:
        return "cross_night_split"
    if len(matched_dates) == 1:
        return "cross_night_boundary_full"
    return "outside_itinerary"


class DayPlanV2(StrictModel):
    day_id: str = Field(min_length=1)
    day: int = Field(ge=1)
    date: Date
    destination_id: str = Field(min_length=1)

    # 标题由实际落位推导，后续编辑不会留下无关标题。
    theme: str = Field(min_length=1)
    timeline: List[TimelineEntryRef]
    time_structure: List[Literal["morning", "lunch", "afternoon", "evening"]] = Field(
        default_factory=lambda: ["morning", "lunch", "afternoon", "evening"]
    )
    estimated_cost_cny: Optional[float] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_time_structure(self) -> "DayPlanV2":
        if self.time_structure != ["morning", "lunch", "afternoon", "evening"]:
            raise ValueError("day plan must retain the four canonical time blocks")
        return self


class StructuredItineraryV2(StrictModel):
    itinerary_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    destination_ids: List[str] = Field(min_length=1)
    duration_days: int = Field(ge=1)
    day_plans: List[DayPlanV2] = Field(min_length=1)
    visit_stops: List[VisitStop] = Field(default_factory=list)
    dining_stops: List[DiningStop] = Field(default_factory=list)
    lodging_stays: List[LodgingStay] = Field(default_factory=list)
    transport_legs: List[TransportLeg] = Field(default_factory=list)
    custom_blocks: List[CustomBlock] = Field(default_factory=list)
    cost_summary: CostCoverageSummary = Field(default_factory=CostCoverageSummary.empty)
    highlights: List[str] = Field(default_factory=list)
    important_notes: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> "StructuredItineraryV2":
        expected_cost_summary = build_cost_coverage_summary(
            itinerary_price_components(
                visit_stops=self.visit_stops,
                dining_stops=self.dining_stops,
                lodging_stays=self.lodging_stays,
                transport_legs=self.transport_legs,
            ),
            budget_cap_cny=self.cost_summary.budget_cap_cny,
            llm_estimated_total_cny=self.cost_summary.llm_estimated_total_cny,
        )
        if "cost_summary" not in self.model_fields_set:
            object.__setattr__(self, "cost_summary", expected_cost_summary)
        elif self.cost_summary != expected_cost_summary:
            raise ValueError("cost summary must match itinerary price coverage")
        for label, identifiers in (
            ("visit stop", [item.item_id for item in self.visit_stops]),
            ("dining stop", [item.item_id for item in self.dining_stops]),
            ("lodging stay", [item.stay_id for item in self.lodging_stays]),
            ("transport leg", [item.transport_leg_id for item in self.transport_legs]),
            ("custom block", [item.item_id for item in self.custom_blocks]),
        ):
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{label} ids must be unique")
        entities: Dict[EntityType, set[str]] = {
            EntityType.VISIT_STOP: {item.item_id for item in self.visit_stops},
            EntityType.DINING_STOP: {item.item_id for item in self.dining_stops},
            EntityType.LODGING_STAY: {item.stay_id for item in self.lodging_stays},
            EntityType.TRANSPORT_LEG: {
                item.transport_leg_id for item in self.transport_legs
            },
            EntityType.CUSTOM_BLOCK: {item.item_id for item in self.custom_blocks},
            EntityType.TRANSPORT_SEGMENT: set(),
        }
        seen: set[tuple[str, EntityType, str, str]] = set()
        transport_projections: Dict[str, List[tuple[Optional[Date], str]]] = {}
        for day in self.day_plans:
            for ref in day.timeline:
                if ref.entity_type == EntityType.TRANSPORT_SEGMENT:
                    raise ValueError("transport segments cannot be timeline roots")
                if ref.entity_id not in entities[ref.entity_type]:
                    raise ValueError(
                        f"dangling timeline reference: {ref.entity_type}/{ref.entity_id}"
                    )
                key = (day.day_id, ref.entity_type, ref.entity_id, ref.projection_role)
                if key in seen:
                    raise ValueError("duplicate entity projection in day timeline")
                seen.add(key)
                if ref.entity_type == EntityType.TRANSPORT_LEG:
                    if ref.projection_role not in {"full", "departure", "arrival"}:
                        raise ValueError(
                            "transport timeline has an invalid projection role"
                        )
                    transport_projections.setdefault(ref.entity_id, []).append(
                        (day.date, ref.projection_role)
                    )
                elif ref.entity_type == EntityType.LODGING_STAY:
                    if ref.projection_role not in {"check_in", "check_out"}:
                        raise ValueError(
                            "lodging timeline has an invalid projection role"
                        )
                elif ref.projection_role != "full":
                    raise ValueError(
                        "ordinary timeline entities require the full projection role"
                    )
        for leg in self.transport_legs:
            projections = transport_projections.get(leg.transport_leg_id, [])
            departure_date = leg.departure_at.date() if leg.departure_at else None
            arrival_date = leg.arrival_at.date() if leg.arrival_at else None
            projection_shape = classify_transport_projection_shape(
                transport_class=leg.transport_class,
                departure_at=leg.departure_at,
                arrival_at=leg.arrival_at,
                itinerary_dates=(day.date for day in self.day_plans),
            )
            if projection_shape == "cross_night_split":
                expected_projections = {
                    (departure_date, "departure"),
                    (arrival_date, "arrival"),
                }
                if len(projections) != 2 or set(projections) != expected_projections:
                    raise ValueError(
                        "cross-night long-distance transport requires departure and arrival Day projections"
                    )
            elif projection_shape == "cross_night_boundary_full":
                itinerary_dates = {day.date for day in self.day_plans}
                boundary_date = next(
                    item
                    for item in (departure_date, arrival_date)
                    if item in itinerary_dates
                )
                if projections != [(boundary_date, "full")]:
                    raise ValueError(
                        "boundary-crossing long-distance transport requires one full projection on its itinerary Day"
                    )
            elif projection_shape == "outside_itinerary":
                raise ValueError(
                    "long-distance transport service dates fall outside the itinerary"
                )
            elif len(projections) != 1 or projections[0][1] != "full":
                raise ValueError(
                    "same-day or local transport requires exactly one full Day projection"
                )
        day_dates = {day.day_id: day.date for day in self.day_plans}
        if len(day_dates) != len(self.day_plans):
            raise ValueError("day plan ids must be unique")
        if self.duration_days != len(self.day_plans):
            raise ValueError("duration_days must equal number of day plans")
        return self
