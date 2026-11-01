"""当前规划版本。"""

from __future__ import annotations

from pydantic import Field

from travel_agent.schema import StrictModel


class PlanningGeneration(StrictModel):
    generation_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
