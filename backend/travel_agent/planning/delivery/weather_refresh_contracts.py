"""Planning delivery weather refresh contracts."""

from __future__ import annotations

from dataclasses import dataclass
from travel_agent.planning.delivery.bundle import DeliveryBundle


WEATHER_SNAPSHOT_INCONSISTENT = "weather_snapshot_inconsistent"


class WeatherRefreshRefused(RuntimeError):
    """A recomputed weather view cannot be safely committed for this Bundle.

    Carries a machine-readable ``code`` from the same vocabulary the Candidate
    re-admission boundary uses (``candidate_evidence_missing`` and friends),
    plus ``weather_snapshot_inconsistent`` for a recomputed snapshot that the
    Delivery Bundle contract itself rejects.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class WeatherBundleRefreshResult:
    bundle: DeliveryBundle
    attempted: bool
    committed: bool
    used_previous_values: bool

    refusal_reason: str | None = None
