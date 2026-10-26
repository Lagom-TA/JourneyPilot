from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Callable, Literal, Optional, Union

from pydantic import Field, model_validator

from travel_agent.planning.itinerary.day_design_contracts import DayDesign
from travel_agent.schema import StrictModel


_SERVER_OWNED_PLACE_FIELDS = (
    "resolved_place_id",
    "resolved_address",
    "resolved_latitude",
    "resolved_longitude",
)


class AuthoredPlaceBase(StrictModel):
    """撰写实体的身份；其中 ``resolved_*`` 字段由地点 Provider 填充。"""

    name: str = Field(min_length=1)
    local_name: str = Field(min_length=1)
    address: str = Field(min_length=1)
    city: str = Field(min_length=1)
    selection_reason: str = Field(min_length=1)
    resolved_place_id: Optional[str] = None
    resolved_address: Optional[str] = None
    resolved_latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    resolved_longitude: Optional[float] = Field(default=None, ge=-180, le=180)

    @property
    def is_located(self) -> bool:
        return (
            bool(self.resolved_place_id)
            and self.resolved_latitude is not None
            and self.resolved_longitude is not None
        )


class AuthoredVisitPlace(AuthoredPlaceBase):
    visit_type: Literal[
        "attraction", "experience", "culture", "shopping", "nature", "other"
    ]
    highlights: list[str] = Field(min_length=1, max_length=4)


class AuthoredDiningPlace(AuthoredPlaceBase):
    cuisine_types: list[str] = Field(min_length=1, max_length=4)
    recommended_dishes: list[str] = Field(min_length=1, max_length=4)


AUTHORED_ROUTE_CLASS_BY_MODE: dict[str, str] = {
    "walk": "flexible",
    "bike": "flexible",
    "drive": "flexible",
    "taxi": "flexible",
    "ride_hailing": "flexible",
    "metro": "public_transit",
    "bus": "public_transit",
    "tram": "public_transit",
}


class AuthoredRoute(StrictModel):
    """撰写的出行方式与时长；起终点由相邻停留点决定。"""

    mode: Literal[
        "walk", "bike", "drive", "taxi", "ride_hailing", "metro", "bus", "tram"
    ]
    duration_minutes: int = Field(ge=1, le=360)
    selection_reason: str = Field(min_length=1)

    @property
    def transport_class(self) -> str:
        return AUTHORED_ROUTE_CLASS_BY_MODE[self.mode]


def _validate_placement_origin(
    candidate_id: Optional[str],
    authored: Optional[object],
    kind: str,
) -> None:
    if bool(candidate_id) == (authored is not None):
        raise ValueError(
            f"{kind} placement takes either an admitted candidate_id or an authored entry"
        )


class VisitPlacement(StrictModel):
    placement_kind: Literal["visit"] = "visit"
    candidate_id: Optional[str] = Field(default=None, min_length=1)
    authored_place: Optional[AuthoredVisitPlace] = None
    planned_start: Optional[datetime] = None
    planned_end: Optional[datetime] = None
    duration_minutes: int = Field(ge=1)
    selection_reason: Optional[str] = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_origin(self) -> "VisitPlacement":
        _validate_placement_origin(self.candidate_id, self.authored_place, "visit")
        return self


class DiningPlacement(StrictModel):
    placement_kind: Literal["dining"] = "dining"
    candidate_id: Optional[str] = Field(default=None, min_length=1)
    authored_place: Optional[AuthoredDiningPlace] = None
    planned_start: Optional[datetime] = None
    planned_end: Optional[datetime] = None
    duration_minutes: int = Field(ge=1)
    selection_reason: Optional[str] = Field(default=None, min_length=1)
    meal_type: Literal["breakfast", "lunch", "dinner", "snack", "other"]

    @model_validator(mode="after")
    def validate_origin(self) -> "DiningPlacement":
        _validate_placement_origin(self.candidate_id, self.authored_place, "dining")
        return self


class TransportPlacement(StrictModel):
    placement_kind: Literal["transport"] = "transport"
    candidate_id: Optional[str] = Field(default=None, min_length=1)
    authored_route: Optional[AuthoredRoute] = None
    connector_gap_id: Optional[str] = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_origin(self) -> "TransportPlacement":
        _validate_placement_origin(self.candidate_id, self.authored_route, "transport")
        return self


CompositionPlacement = Annotated[
    Union[VisitPlacement, DiningPlacement, TransportPlacement],
    Field(discriminator="placement_kind"),
]


PhysicalPlacement = Union[VisitPlacement, DiningPlacement]


@dataclass(frozen=True)
class LodgingBoundary:
    """由选定住宿生成的带日期路线端点。"""

    candidate_id: str
    role: Literal["morning", "evening"]
    planned_start: datetime
    planned_end: datetime
    placement_kind: Literal["lodging"] = "lodging"


ChainNode = Union[CompositionPlacement, LodgingBoundary]


def is_authored_placement(placement: CompositionPlacement) -> bool:
    if placement.placement_kind in {"visit", "dining"}:
        return placement.authored_place is not None
    if placement.placement_kind == "transport":
        return placement.authored_route is not None
    return False


def placement_identity(placement: ChainNode) -> Optional[str]:
    if isinstance(placement, LodgingBoundary):
        return f"lodging:{placement.candidate_id}:{placement.role}"
    if placement.candidate_id:
        return f"candidate:{placement.candidate_id}"
    if placement.placement_kind == "transport":
        return None
    authored = placement.authored_place
    return f"authored:{authored.city}:{authored.name}"


def placement_occurrence_key(day_id: str, placement: ChainNode) -> str:
    if isinstance(placement, TransportPlacement) and placement.connector_gap_id:
        return placement.connector_gap_id
    return _stable_id(
        "occurrence",
        day_id,
        placement_identity(placement),
        getattr(placement, "meal_type", None),
        getattr(placement, "planned_start", None),
        getattr(placement, "planned_end", None),
    )


class DayComposition(StrictModel):
    day_id: str = Field(min_length=1)
    day: int = Field(ge=1)
    date: date
    destination_id: str = Field(min_length=1)
    day_design: Optional[DayDesign] = None
    placements: list[CompositionPlacement] = Field(min_length=1)
    time_structure: list[Literal["morning", "lunch", "afternoon", "evening"]] = Field(
        default_factory=lambda: ["morning", "lunch", "afternoon", "evening"]
    )

    @model_validator(mode="after")
    def validate_time_structure(self) -> "DayComposition":
        if self.time_structure != ["morning", "lunch", "afternoon", "evening"]:
            raise ValueError(
                "composition day must retain the four canonical time blocks"
            )
        return self


class ItineraryCompositionDraft(StrictModel):
    itinerary_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    duration_days: int = Field(ge=1)
    days: list[DayComposition] = Field(min_length=1)
    lodging_candidate_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_days(self) -> "ItineraryCompositionDraft":
        if self.duration_days != len(self.days):
            raise ValueError("composition duration must equal day count")
        if [day.day for day in self.days] != list(range(1, len(self.days) + 1)):
            raise ValueError("composition days must be contiguous from one")
        ids = [day.day_id for day in self.days]
        if len(ids) != len(set(ids)):
            raise ValueError("composition day ids must be unique")
        for day in self.days:
            occurrences = set()
            meals = set()
            for placement in day.placements:
                start = getattr(placement, "planned_start", None)
                end = getattr(placement, "planned_end", None)
                if (start is None) != (end is None):
                    raise ValueError("scheduled placement requires both start and end")
                if start is not None:
                    if start.utcoffset() is None or end.utcoffset() is None:
                        raise ValueError(
                            "placement schedule requires a timezone UTC offset on both ends"
                        )
                    if (
                        end <= start
                        or start.date() != day.date
                        or end.date() != day.date
                    ):
                        raise ValueError(
                            "placement schedule must be ordered within its local day"
                        )
                key = placement_identity(placement)
                if key is not None:
                    occurrence = placement_occurrence_key(day.day_id, placement)
                    if occurrence in occurrences:
                        raise ValueError(
                            "an entry cannot be placed more than once at the same time"
                        )
                    occurrences.add(occurrence)
                    if placement.placement_kind == "dining":
                        meal = (key, placement.meal_type)
                        if meal in meals:
                            raise ValueError(
                                "duplicate restaurant for the same meal in one day"
                            )
                        meals.add(meal)
            scheduled = [
                placement
                for placement in day.placements
                if placement.placement_kind in {"visit", "dining"}
                and placement.planned_start is not None
            ]
            for left, right in zip(scheduled, scheduled[1:]):
                if right.planned_start < left.planned_end:
                    raise ValueError(
                        "scheduled placements overlap or do not follow itinerary order"
                    )
        return self


class ItineraryCompositionError(ValueError):
    pass


def _stable_id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest()[
        :16
    ]
    return f"{prefix}_{digest}"


@dataclass(frozen=True)
class AuthoredPlaceRef:
    """一个撰写地点及其解析所需的天上下文。"""

    place: AuthoredPlaceBase
    destination_id: str
    kind: str


def authored_places(composition: ItineraryCompositionDraft) -> list[AuthoredPlaceRef]:
    """按行程顺序列出全部撰写地点，并带上所属天的上下文。"""
    return [
        AuthoredPlaceRef(
            place=placement.authored_place,
            destination_id=day.destination_id,
            kind=placement.placement_kind,
        )
        for day in composition.days
        for placement in day.placements
        if placement.placement_kind in {"visit", "dining"}
        and placement.authored_place is not None
    ]


def authored_place_key(place: AuthoredPlaceBase) -> str:
    return f"authored:{place.city}:{place.name}"


def map_authored_places(
    composition: ItineraryCompositionDraft,
    replace: Callable[[AuthoredPlaceBase], AuthoredPlaceBase],
) -> ItineraryCompositionDraft:
    """重建 composition，对每个撰写地点调用 ``replace``。"""
    days: list[DayComposition] = []
    for day in composition.days:
        placements: list[CompositionPlacement] = []
        for placement in day.placements:
            if (
                placement.placement_kind in {"visit", "dining"}
                and placement.authored_place is not None
            ):
                updated = replace(placement.authored_place)
                if updated is not placement.authored_place:
                    placement = placement.model_copy(update={"authored_place": updated})
            placements.append(placement)
        days.append(day.model_copy(update={"placements": placements}))
    return composition.model_copy(update={"days": days})
