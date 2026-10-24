from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import Field, model_validator

from travel_agent.schema import StrictModel


class TransportEndpoint(StrictModel):
    name: str = Field(min_length=1)
    place_id: Optional[str] = None
    station_code: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)


class TransportMode(str, Enum):
    FLIGHT = "flight"
    HIGH_SPEED_RAIL = "high_speed_rail"
    TRAIN = "train"
    COACH = "coach"
    FERRY = "ferry"
    METRO = "metro"
    BUS = "bus"
    TRAM = "tram"
    TAXI = "taxi"
    RIDE_HAILING = "ride_hailing"
    DRIVE = "drive"
    BIKE = "bike"
    WALK = "walk"
    OTHER = "other"


class TransportSegment(StrictModel):
    segment_id: str = Field(min_length=1)
    mode: TransportMode
    from_endpoint: TransportEndpoint
    to_endpoint: TransportEndpoint
    departure_at: Optional[datetime] = None
    arrival_at: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(default=None, ge=0)
    distance_meters: Optional[int] = Field(default=None, ge=0)
    operator_name: Optional[str] = None
    service_number: Optional[str] = None
    line_name: Optional[str] = None
    cost_cny: Optional[float] = Field(default=None, ge=0)


class TransportModePreference(StrictModel):
    locked_mode: Optional[TransportMode] = None
    excluded_modes: List[TransportMode] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_lock(self) -> "TransportModePreference":
        if self.locked_mode is not None and self.locked_mode in self.excluded_modes:
            raise ValueError("locked transport mode cannot also be excluded")
        return self
