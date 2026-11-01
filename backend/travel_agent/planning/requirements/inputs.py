from __future__ import annotations

from datetime import date as Date
from datetime import datetime, timedelta
from typing import Any, List, Literal, Optional

from pydantic import Field, model_validator

from travel_agent.schema import StrictModel


class UserInputAnchor(StrictModel):
    anchor_id: str = Field(min_length=1)
    field_path: str = Field(min_length=1)
    value: Any
    input_kind: Literal["controlled_identity", "requirements", "planning_authorization"]


class MinimumDeliveryDayShell(StrictModel):
    day_id: str = Field(min_length=1)
    day: int = Field(ge=1)
    date: Date
    destination_id: str = Field(min_length=1)
    lodging_night: bool = False
    arrival_from_destination_id: Optional[str] = None
    time_structure: List[Literal["morning", "lunch", "afternoon", "evening"]] = Field(
        default_factory=lambda: ["morning", "lunch", "afternoon", "evening"]
    )


class MinimumDeliveryDraft(StrictModel):
    draft_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    planning_generation_id: str = Field(min_length=1)
    day_shells: List[MinimumDeliveryDayShell] = Field(min_length=1)
    user_input_anchors: List[UserInputAnchor] = Field(default_factory=list)
    planning_authorized: bool = False
    planning_authorized_at: Optional[datetime] = None
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_draft(self) -> "MinimumDeliveryDraft":
        if [item.day for item in self.day_shells] != list(range(1, len(self.day_shells) + 1)):
            raise ValueError("行程天数必须连续")
        dates = [item.date for item in self.day_shells]
        if dates != [dates[0] + timedelta(days=index) for index in range(len(dates))]:
            raise ValueError("行程日期必须连续")
        if len({item.day_id for item in self.day_shells}) != len(self.day_shells):
            raise ValueError("行程日期标识不能重复")
        if [item.lodging_night for item in self.day_shells] != [index < len(self.day_shells) - 1 for index in range(len(self.day_shells))]:
            raise ValueError("住宿夜数与行程日期不一致")
        if self.planning_authorized != (self.planning_authorized_at is not None):
            raise ValueError("方案确认状态与确认时间不一致")
        return self
