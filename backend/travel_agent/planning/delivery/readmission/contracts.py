"""Planning delivery readmission contracts."""

from __future__ import annotations

from dataclasses import dataclass
from travel_agent.planning.research.candidates import CandidateAdmissionResult
from travel_agent.planning.research.candidates import ResearchCandidate
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.planning.weather.models import WeatherImpact


class CandidateReadmissionError(RuntimeError):
    """A current Bundle cannot safely yield re-admitted Candidate evidence."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CandidateCatalogReadmissionResult:
    """A non-persisted, whole-Catalog re-admission view for named Candidates.

    This is the shared safety boundary for every public path that turns a
    Candidate into a canonical itinerary entity.  It deliberately does not
    choose or promote anything: callers must compare the returned catalog and
    weather impacts with the current Bundle, then require an explicit refresh
    when that comparison exposes stale evidence.
    """

    candidate_ids: tuple[str, ...]
    catalog: RecommendationCatalog
    weather_impacts: tuple[WeatherImpact, ...]


@dataclass(frozen=True)
class CandidateCurrentnessResult:
    """Currentness checks for specific Candidate-to-canonical materializations."""

    candidate_ids: tuple[str, ...]
    candidates: tuple[ResearchCandidate, ...]
    admissions: tuple[CandidateAdmissionResult, ...]
    weather_impacts: tuple[WeatherImpact, ...]
    catalog_changed: bool
