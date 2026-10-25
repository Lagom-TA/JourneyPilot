"""Planning research admission assessment."""

from __future__ import annotations

from datetime import date
from travel_agent.planning.research.admission.identity import (
    _missing_concrete_identity_fields,
)
from travel_agent.planning.research.admission.identity import (
    _out_of_destination_identity_fields,
)
from travel_agent.planning.research.admission.lodging import _lodging_budget_fit
from travel_agent.planning.research.admission.scoring import _constraint_fit
from travel_agent.planning.research.admission.scoring import _weather_fit
from travel_agent.planning.research.candidates import CandidateAdmissionResult
from travel_agent.planning.research.candidates import CandidateFitScores
from travel_agent.planning.research.candidates import ResearchCandidate
from travel_agent.planning.research.evidence import FactAssertion
from travel_agent.planning.research.evidence import SourceRecord
from travel_agent.planning.weather.models import WeatherImpact
from typing import Any
from typing import Iterable
from typing import Mapping
from typing import Optional
from typing import Sequence


def admit_candidate(
    candidate: ResearchCandidate,
    *,
    fact_data_revision: int,
    weather_data_revision: int,
    selection_slot_id: Optional[str] = None,
    weather_impacts: Iterable[WeatherImpact] = (),
    weather_evaluated_dates: Iterable[date] = (),
    expected_destination_country_code: Optional[str] = None,
    require_destination_country_scope: bool = True,
    destination_point: Optional[tuple[float, float]] = None,
    identity_fact_values: Mapping[str, Sequence[Any]],
    hard_constraints: Iterable[Mapping[str, Any]] = (),
    candidate_facts: Iterable[FactAssertion] = (),
    source_records: Iterable[SourceRecord] = (),
) -> CandidateAdmissionResult:
    """Normalize one candidate into the catalog and score how well it fits.

    A concrete identity — a name, a resolvable place, a provider type matching
    the candidate kind — is what admission asserts. Budget, weather and
    constraint outcomes ride along as 0–1 ranking signals so composition can
    prefer the better option instead of losing the entity.

    ``candidate_facts`` and ``source_records`` are the evidence admission reads
    directly: a required field whose truth cannot be re-derived from a
    server-compiled source is treated as absent, not as asserted.
    """

    impacts = list(weather_impacts)
    evaluated_dates = set(weather_evaluated_dates)
    impact_ids = [impact.weather_impact_id for impact in impacts]
    if set(impact_ids) != set(candidate.weather_impact_ids):
        raise ValueError(
            "candidate must carry the exact weather impacts evaluated by admission"
        )
    facts = list(candidate_facts)
    sources = list(source_records)
    missing_fields = _missing_concrete_identity_fields(
        candidate,
        identity_fact_values,
        candidate_facts=facts,
        source_records=sources,
    )

    if require_destination_country_scope:
        missing_fields = missing_fields + [
            field
            for field in _out_of_destination_identity_fields(
                candidate,
                destination_point=destination_point,
                identity_fact_values=identity_fact_values,
            )
            if field not in missing_fields
        ]
    fit_scores = CandidateFitScores(
        budget_fit=_lodging_budget_fit(
            candidate,
            hard_constraints=hard_constraints,
            candidate_facts=facts,
            source_records=sources,
        ),
        weather_fit=_weather_fit(impacts, evaluated_dates),
        constraint_fit=_constraint_fit(
            candidate,
            expected_destination_country_code=expected_destination_country_code,
            require_destination_country_scope=require_destination_country_scope,
        ),
    )
    common = dict(
        candidate_id=candidate.candidate_id,
        selection_slot_id=selection_slot_id,
        evaluated_fact_revision=fact_data_revision,
        evaluated_weather_revision=weather_data_revision,
        weather_impact_ids=impact_ids,
        checked_constraint_ids=list(candidate.active_constraint_ids),
        fit_scores=fit_scores,
    )
    if missing_fields:
        return CandidateAdmissionResult(
            **common,
            status="insufficient_for_admission",
            missing_field_paths=missing_fields,
        )
    return CandidateAdmissionResult(**common, status="passed")
