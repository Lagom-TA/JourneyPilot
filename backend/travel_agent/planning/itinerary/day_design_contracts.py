from __future__ import annotations

from datetime import datetime
from pydantic import Field
from pydantic import model_validator
from travel_agent.schema import StrictModel


class PlannedFreeTime(StrictModel):
    planned_start: datetime
    planned_end: datetime

    @model_validator(mode="after")
    def validate_window(self):
        if (
            self.planned_start.utcoffset() is None
            or self.planned_end.utcoffset() is None
            or self.planned_end <= self.planned_start
            or self.planned_end.date() != self.planned_start.date()
        ):
            raise ValueError(
                "free time needs an ordered, timezone-aware local day window"
            )
        return self


class DayDesign(StrictModel):
    free_time: list[PlannedFreeTime] = Field(default_factory=list, max_length=8)
    # 当天确实无法安排的具体事项：研究或补查后仍缺支撑时如实写出，
    # 服务器保留到工作台的重要说明，不把缺口伪装成完整安排。
    unresolved: list[str] = Field(default_factory=list, max_length=8)
