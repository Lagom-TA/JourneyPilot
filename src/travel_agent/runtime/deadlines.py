from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from travel_agent.schema import StrictModel


class RunDeadlineSnapshot(StrictModel):
    # Embedded windows keep validation independent of later configuration changes.
    draft_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    planning_authorized_at: datetime
    target_at: datetime
    closeout_at: datetime
    composition_at: datetime
    delivery_deadline_at: datetime
    target_seconds: int = Field(ge=1)
    closeout_seconds: int = Field(ge=1)
    composition_seconds: int = Field(ge=1)
    delivery_deadline_seconds: int = Field(ge=1)
    checkpointed_elapsed_seconds: float = Field(ge=0)
    last_observed_at: datetime

    @model_validator(mode="after")
    def validate_deadlines(self) -> "RunDeadlineSnapshot":
        if any(
            value.tzinfo is None
            for value in (
                self.planning_authorized_at,
                self.target_at,
                self.closeout_at,
                self.composition_at,
                self.delivery_deadline_at,
                self.last_observed_at,
            )
        ):
            raise ValueError("run deadlines must use timezone-aware timestamps")
        if not (
            self.planning_authorized_at
            < self.target_at
            < self.closeout_at
            < self.composition_at
            < self.delivery_deadline_at
        ):
            raise ValueError("run deadlines must be strictly ordered")
        if not (
            self.target_seconds
            < self.closeout_seconds
            < self.composition_seconds
            < self.delivery_deadline_seconds
        ):
            raise ValueError("run deadline windows must be strictly increasing")
        if (
            self.target_at - self.planning_authorized_at
        ).total_seconds() != self.target_seconds:
            raise ValueError("run target must match the snapshot target window")
        if (
            self.closeout_at - self.planning_authorized_at
        ).total_seconds() != self.closeout_seconds:
            raise ValueError("run closeout must match the snapshot closeout window")
        if (
            self.composition_at - self.planning_authorized_at
        ).total_seconds() != self.composition_seconds:
            raise ValueError(
                "run composition must match the snapshot composition window"
            )
        if (
            self.delivery_deadline_at - self.planning_authorized_at
        ).total_seconds() != self.delivery_deadline_seconds:
            raise ValueError(
                "run delivery deadline must match the snapshot delivery window"
            )
        if self.last_observed_at < self.planning_authorized_at:
            raise ValueError("deadline observation predates planning authorization")
        return self
