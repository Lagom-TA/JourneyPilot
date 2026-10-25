"""Validated trip planner product contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PlannerOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    inference_keywords: list[str] = Field(default_factory=list)
    is_default: bool = False


class TripPlannerConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_styles: list[PlannerOption] = Field(min_length=1)
    secondary_interests: list[PlannerOption] = Field(default_factory=list)
    default_adults: int = Field(ge=1, le=20)
    default_children: int = Field(ge=0, le=20)
    default_elderly_companions: bool
    default_accessibility_required: bool
    max_secondary_interests: int = Field(ge=0, le=10)
    inspiration_rotation_ms: int = Field(ge=3000, le=30000)
    inspiration_prompts: list[str] = Field(min_length=3)

    @model_validator(mode="after")
    def validate_defaults(self) -> "TripPlannerConfiguration":
        if sum(option.is_default for option in self.primary_styles) != 1:
            raise ValueError("primary_styles must contain exactly one default")
        if len({option.id for option in self.primary_styles}) != len(
            self.primary_styles
        ):
            raise ValueError("primary style ids must be unique")
        if len({option.id for option in self.secondary_interests}) != len(
            self.secondary_interests
        ):
            raise ValueError("secondary interest ids must be unique")
        if any(not prompt.strip() for prompt in self.inspiration_prompts):
            raise ValueError("inspiration prompts cannot be blank")
        return self


TRIP_PLANNER_CONFIG_KEY = "trip_planner"
