"""Planning research admission scoring."""

from __future__ import annotations

from datetime import date
from travel_agent.planning.research.candidates import DiningCandidate
from travel_agent.planning.research.candidates import LodgingCandidate
from travel_agent.planning.research.candidates import ResearchCandidate
from travel_agent.planning.research.candidates import VisitCandidate
from travel_agent.planning.weather.impacts import day_weather_fit
from travel_agent.planning.weather.models import WeatherImpact
from typing import Optional
from typing import Sequence


_UNKNOWN_CONSTRAINT_FIT = 0.5


_OUT_OF_SCOPE_CONSTRAINT_FIT = 0.1


def _weather_fit(
    impacts: Sequence[WeatherImpact],
    evaluated_dates: set[date],
) -> float:
    """Average how suitable each evaluated day is for this candidate.

    An unscheduled candidate evaluated across the whole stay keeps a usable
    score as long as some day suits it; composition reads that score to put
    exposed options on the clearest days.
    """

    dates = set(evaluated_dates) or {impact.date for impact in impacts}
    if not dates:
        return 1.0
    return sum(
        day_weather_fit([impact for impact in impacts if impact.date == day])
        for day in dates
    ) / len(dates)


def _constraint_fit(
    candidate: ResearchCandidate,
    *,
    expected_destination_country_code: Optional[str],
    require_destination_country_scope: bool,
) -> float:
    """Score the candidate against the active hard constraints and trip scope."""

    evaluations = {
        item.constraint_id: item for item in candidate.constraint_evaluations
    }
    active = list(candidate.active_constraint_ids)
    if active:
        scores = []
        for constraint_id in active:
            evaluation = evaluations.get(constraint_id)
            if evaluation is None or evaluation.status == "unknown":
                scores.append(_UNKNOWN_CONSTRAINT_FIT)
            elif evaluation.status == "failed":
                scores.append(0.0)
            else:
                scores.append(1.0)
        fit = sum(scores) / len(scores)
    else:
        fit = 1.0
    if require_destination_country_scope and isinstance(
        candidate, (DiningCandidate, LodgingCandidate, VisitCandidate)
    ):
        expected_country = (expected_destination_country_code or "").strip().casefold()
        if (
            not expected_country
            or candidate.provider_country_code.strip().casefold() != expected_country
        ):
            fit = min(fit, _OUT_OF_SCOPE_CONSTRAINT_FIT)
    return fit
