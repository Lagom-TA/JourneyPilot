"""Planning delivery readmission selected."""

from __future__ import annotations

from datetime import datetime
from travel_agent.planning.delivery.bundle import DeliveryBundle
from travel_agent.planning.delivery.readmission.contracts import (
    CandidateCurrentnessResult,
)
from travel_agent.planning.delivery.readmission.contracts import (
    CandidateReadmissionError,
)
from travel_agent.planning.delivery.readmission.evidence import (
    _assert_catalog_is_not_future,
)
from travel_agent.planning.delivery.readmission.evidence import _current_packet
from travel_agent.planning.delivery.readmission_freshness import _aware
from travel_agent.planning.delivery.readmission_freshness import _target_ref
from travel_agent.planning.delivery.readmission_freshness import _weather_days
from travel_agent.planning.requirements.constraint_applicability import (
    active_hard_constraint_ids,
)
from travel_agent.planning.research.admission.assessment import admit_candidate
from travel_agent.planning.research.admission.lodging import (
    normalize_lodging_price_evidence,
)
from travel_agent.planning.research.candidates import CandidateAdmissionResult
from travel_agent.planning.research.candidates import ResearchCandidate
from travel_agent.planning.weather.impacts import WeatherImpactEngine
from travel_agent.planning.weather.impacts import risk_profile_from_constraint_pack
from travel_agent.planning.weather.models import WeatherImpact
from typing import Mapping
from typing import Sequence


def readmit_current_candidates(
    bundle: DeliveryBundle,
    *,
    candidate_scopes: Mapping[str, Sequence[str | None]],
    constraint_pack: Mapping[str, object] | None = None,
    destination_country_codes: Mapping[str, str] | None = None,
    as_of: datetime | None = None,
) -> CandidateCurrentnessResult:
    """Check only the Candidate lineages a pending mutation will materialize.

    Unlike a formal refresh this never manufactures a new whole Catalog.  That
    matters for an ordinary selection: an unrelated expired Candidate must not
    prevent the user from applying a currently verified one.  Each requested
    Candidate and its exact selection scope is still independently rebound to
    current facts, source/cache validity, weather, and applicable hard
    constraints.  Any difference from the durable catalog tells the caller to
    require an explicit refresh rather than silently committing it.
    """

    _assert_catalog_is_not_future(bundle)
    normalized_scopes = {
        str(candidate_id): tuple(dict.fromkeys(scopes))
        for candidate_id, scopes in candidate_scopes.items()
    }
    if not normalized_scopes or any(
        not candidate_id or not scopes
        for candidate_id, scopes in normalized_scopes.items()
    ):
        raise CandidateReadmissionError(
            "candidate_not_current",
            "Candidate currentness requires at least one Candidate and admission scope",
        )
    candidate_ids = tuple(normalized_scopes)
    catalog = bundle.workspace.recommendation_catalog
    original_candidates = catalog.candidate_index()
    missing_candidate_ids = [
        candidate_id
        for candidate_id in candidate_ids
        if candidate_id not in original_candidates
    ]
    if missing_candidate_ids:
        raise CandidateReadmissionError(
            "candidate_not_current",
            "Candidate no longer exists in the current Recommendation Catalog",
        )
    as_of = _aware(as_of or bundle.manifest.created_at)
    fact_snapshot = bundle.fact_snapshot
    fact_index = {
        item.fact_assertion_id: item for item in fact_snapshot.fact_assertions
    }
    source_index = {
        item.source_record_id: item for item in fact_snapshot.source_records
    }
    source_order = [item.source_record_id for item in fact_snapshot.source_records]
    provenance_order = {
        id(item): index for index, item in enumerate(fact_snapshot.field_provenance)
    }
    country_codes = {
        str(destination_id): str(country_code)
        for destination_id, country_code in (destination_country_codes or {}).items()
    }
    risk_profile = risk_profile_from_constraint_pack(constraint_pack or {})
    impact_engine = WeatherImpactEngine()
    original_admissions = catalog.admission_index()
    refreshed_candidates: list[ResearchCandidate] = []
    refreshed_admissions: list[CandidateAdmissionResult] = []
    impacts: list[WeatherImpact] = []

    for packet in catalog.research_packets:
        requested = [
            candidate
            for candidate in packet.candidates
            if candidate.candidate_id in normalized_scopes
        ]
        if not requested:
            continue

        packet_slice = packet.model_copy(update={"candidates": requested})
        current_packet = _current_packet(
            packet_slice,
            fact_data_revision=bundle.manifest.fact_data_revision,
            fact_index=fact_index,
            source_index=source_index,
            field_provenance=fact_snapshot.field_provenance,
            source_order=source_order,
            provenance_order=provenance_order,
            constraint_pack=constraint_pack,
            expected_active_constraint_ids=active_hard_constraint_ids(
                constraint_pack,
                worker_kind=packet.worker_kind,
            ),
            as_of=as_of,
        )
        for candidate in current_packet.candidates:
            candidate_facts = [
                item
                for item in current_packet.fact_assertions
                if item.entity_ref.entity_id == candidate.candidate_id
            ]
            candidate = normalize_lodging_price_evidence(
                candidate,
                candidate_facts=candidate_facts,
                source_records=current_packet.source_records,
            )
            candidate_days = _weather_days(bundle.weather_snapshot, candidate)
            candidate_impacts = [
                impact
                for day in candidate_days
                for impact in impact_engine.evaluate(
                    weather_day=day,
                    target_ref=_target_ref(candidate),
                    sensitivity=candidate.weather_sensitivity,
                    risk_profile=risk_profile,
                )
            ]
            refreshed = candidate.model_copy(
                update={
                    "weather_impact_ids": [
                        impact.weather_impact_id for impact in candidate_impacts
                    ]
                }
            )
            refreshed_candidates.append(refreshed)
            impacts.extend(candidate_impacts)
            for selection_slot_id in normalized_scopes[candidate.candidate_id]:
                refreshed_admissions.append(
                    admit_candidate(
                        refreshed,
                        fact_data_revision=bundle.manifest.fact_data_revision,
                        weather_data_revision=bundle.manifest.weather_data_revision,
                        selection_slot_id=selection_slot_id,
                        weather_impacts=candidate_impacts,
                        weather_evaluated_dates=[
                            day.date
                            for day in candidate_days
                            if day.data_kind != "unavailable"
                        ],
                        expected_destination_country_code=country_codes.get(
                            refreshed.destination_id
                        ),
                        identity_fact_values={
                            field_path: [
                                item.asserted_value
                                for item in candidate_facts
                                if item.field_path == field_path
                            ]
                            for field_path in {
                                item.field_path for item in candidate_facts
                            }
                        },
                        hard_constraints=(
                            constraint_pack.get("hard_constraints") or []
                            if isinstance(constraint_pack, Mapping)
                            else []
                        ),
                        candidate_facts=candidate_facts,
                        source_records=current_packet.source_records,
                    )
                )

    refreshed_by_id = {
        candidate.candidate_id: candidate for candidate in refreshed_candidates
    }
    refreshed_admission_index = {
        (item.candidate_id, item.selection_slot_id): item
        for item in refreshed_admissions
    }
    catalog_changed = any(
        refreshed_by_id.get(candidate_id) != original_candidates[candidate_id]
        for candidate_id in candidate_ids
    ) or any(
        refreshed_admission_index.get((candidate_id, selection_slot_id))
        != original_admissions.get((candidate_id, selection_slot_id))
        for candidate_id, scopes in normalized_scopes.items()
        for selection_slot_id in scopes
    )
    return CandidateCurrentnessResult(
        candidate_ids=candidate_ids,
        candidates=tuple(refreshed_candidates),
        admissions=tuple(refreshed_admissions),
        weather_impacts=tuple(
            {item.weather_impact_id: item for item in impacts}.values()
        ),
        catalog_changed=catalog_changed,
    )
