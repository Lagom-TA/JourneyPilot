"""天气 Bundle 刷新契约。"""

from __future__ import annotations

from dataclasses import dataclass
from travel_agent.planning.delivery.bundle import DeliveryBundle


WEATHER_SNAPSHOT_INCONSISTENT = "weather_snapshot_inconsistent"


@dataclass(frozen=True)
class WeatherBundleRefreshResult:
    bundle: DeliveryBundle
    attempted: bool
    committed: bool
    used_previous_values: bool

    refusal_reason: str | None = None
