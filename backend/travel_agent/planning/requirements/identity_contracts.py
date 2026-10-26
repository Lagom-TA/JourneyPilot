"""行程身份契约。"""

from __future__ import annotations

from datetime import date
from enum import Enum
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator
from typing import List
from typing import Literal


class _StrictInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlaceKind(str, Enum):
    CITY = "city"
    ADMINISTRATIVE_AREA = "administrative_area"
    ISLAND = "island"
    SCENIC_AREA = "scenic_area"
    AIRPORT = "airport"
    TRAIN_STATION = "train_station"
    COUNTRY = "country"
    POI = "poi"
    HOTEL = "hotel"
    RESTAURANT = "restaurant"


MAX_CONTROLLED_DESTINATIONS = 3


ORIGIN_PLACE_KINDS = {PlaceKind.CITY, PlaceKind.AIRPORT, PlaceKind.TRAIN_STATION}


DESTINATION_PLACE_KINDS = {
    PlaceKind.CITY,
    PlaceKind.ADMINISTRATIVE_AREA,
    PlaceKind.ISLAND,
    PlaceKind.SCENIC_AREA,
}


ITINERARY_PLACE_KINDS = {
    PlaceKind.SCENIC_AREA,
    PlaceKind.POI,
    PlaceKind.HOTEL,
    PlaceKind.RESTAURANT,
    PlaceKind.TRAIN_STATION,
}


class PlaceIdentity(_StrictInputModel):
    place_id: str = Field(min_length=3)
    provider: Literal["osm", "amap", "manual_verified"]
    kind: PlaceKind
    name: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    country_code: str = Field(min_length=2, max_length=2)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    admin_path: List[str] = Field(default_factory=list)


class TravelParty(_StrictInputModel):
    adults: int = Field(ge=1, le=20)
    children: int = Field(ge=0, le=20)
    elderly_companions: bool = False
    accessibility_required: bool = False


class TravelStyle(_StrictInputModel):
    primary: str = Field(min_length=1)
    secondary_interests: List[str] = Field(default_factory=list)

    source: Literal["current", "suggested"] = "suggested"


class ControlledTripIdentity(_StrictInputModel):
    origin: PlaceIdentity

    destinations: List[PlaceIdentity] = Field(min_length=1)
    start_date: date
    end_date: date
    party: TravelParty
    style: TravelStyle

    @model_validator(mode="after")
    def validate_identity(self) -> "ControlledTripIdentity":
        if self.origin.kind not in ORIGIN_PLACE_KINDS:
            raise ValueError("出发地只支持城市、机场或火车站")
        if len(self.destinations) > MAX_CONTROLLED_DESTINATIONS:
            raise ValueError(f"一次旅行最多 {MAX_CONTROLLED_DESTINATIONS} 个目的地")
        invalid = [
            item.display_name
            for item in self.destinations
            if item.kind not in DESTINATION_PLACE_KINDS
        ]
        if invalid:
            raise ValueError(
                f"目的地只支持城市、行政区域、岛屿或景区型区域: {', '.join(invalid)}"
            )
        if len({item.place_id for item in self.destinations}) != len(self.destinations):
            raise ValueError("目的地不能重复")
        days = (self.end_date - self.start_date).days + 1
        if days < 1:
            raise ValueError("结束日期不能早于开始日期")
        if days > 14:
            raise ValueError("单次旅行最多 14 天")
        if len(self.destinations) > days:
            raise ValueError("目的地数量不能超过行程天数")
        return self

    @property
    def duration_days(self) -> int:
        return (self.end_date - self.start_date).days + 1
