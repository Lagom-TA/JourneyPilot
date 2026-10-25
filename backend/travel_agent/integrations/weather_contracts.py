"""Integrations weather_contracts."""

from __future__ import annotations

from datetime import datetime
from pydantic import Field
from pydantic import model_validator
from travel_agent.schema import StrictModel
from typing import Optional


class WeatherTimeWindow(StrictModel):
    start_at: datetime
    end_at: datetime
    precipitation_probability_pct: Optional[float] = Field(default=None, ge=0, le=100)
    apparent_temperature_c: Optional[float] = None
    wind_speed_kph: Optional[float] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_window(self) -> "WeatherTimeWindow":
        if self.end_at <= self.start_at:
            raise ValueError("weather time window must end after it starts")
        return self
