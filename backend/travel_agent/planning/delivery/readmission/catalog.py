"""Planning delivery readmission catalog."""

from __future__ import annotations

from datetime import datetime
from travel_agent.planning.delivery.bundle import DeliveryBundle
from travel_agent.planning.delivery.readmission.contracts import (
    CandidateCatalogReadmissionResult,
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
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.planning.weather.impacts import WeatherImpactEngine
from travel_agent.planning.weather.impacts import risk_profile_from_constraint_pack
from travel_agent.planning.weather.models import WeatherImpact
from typing import Mapping
from typing import Sequence


def readmit_current_catalog_candidates(
    bundle: DeliveryBundle,
    *,
    candidate_ids: Sequence[str],
    constraint_pack: Mapping[str, object] | None = None,
    destination_country_codes: Mapping[str, str] | None = None,
    as_of: datetime | None = None,
    allow_fact_revision_rebind: bool = False,
    allow_unanchored_existing_identity: bool = False,
) -> CandidateCatalogReadmissionResult:
    """Re-evaluate named Candidate evidence without a provider call or mutation.

    The full current catalog is re-admitted, rather than only the requested
    records.  This intentionally fails closed if any packet has become
    inconsistent: a catalog revision must never mix a freshly evaluated
    Candidate with historical admission or constraint verdicts.
    """
    _assert_catalog_is_not_future(bundle)
    candidate_ids = tuple(candidate_ids)
    if not candidate_ids or len(candidate_ids) != len(set(candidate_ids)):
        raise CandidateReadmissionError(
            "candidate_not_current",
            "Candidate re-admission requires one or more unique candidate ids",
        )
    catalog = bundle.workspace.recommendation_catalog
    candidate_index = catalog.candidate_index()
    missing_candidate_ids = [
        candidate_id
        for candidate_id in candidate_ids
        if candidate_id not in candidate_index
    ]
    if missing_candidate_ids:
        raise CandidateReadmissionError(
            "candidate_not_current",
            "Candidate no longer exists in the current Recommendation Catalog",
        )

    as_of = _aware(as_of or bundle.manifest.created_at)

    fact_snapshot = bundle.fact_snapshot
    weather_snapshot = bundle.weather_snapshot
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
    target_packet_ids = {
        packet.research_packet_id for packet in catalog.research_packets
    }
    packets = [
        _current_packet(
            packet,
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
            allow_fact_revision_rebind=allow_fact_revision_rebind,
        )
        if packet.research_packet_id in target_packet_ids
        else packet
        for packet in bundle.workspace.recommendation_catalog.research_packets
    ]

    impacts: list[WeatherImpact] = []
    target_candidate_ids = {
        candidate.candidate_id
        for packet in catalog.research_packets
        if packet.research_packet_id in target_packet_ids
        for candidate in packet.candidates
    }
    admissions: list[CandidateAdmissionResult] = [
        item
        for item in bundle.workspace.recommendation_catalog.admission_results
        if item.candidate_id not in target_candidate_ids
    ]
    updated_packets: list[ResearchPacket] = []
    risk_profile = risk_profile_from_constraint_pack(constraint_pack or {})
    impact_engine = WeatherImpactEngine()
    previous_scopes_by_candidate: dict[str, list[str | None]] = {}
    for previous in catalog.admission_results:
        previous_scopes_by_candidate.setdefault(previous.candidate_id, []).append(
            previous.selection_slot_id
        )
    country_codes = {
        str(destination_id): str(country_code)
        for destination_id, country_code in (destination_country_codes or {}).items()
    }

    for packet in packets:
        if packet.research_packet_id not in target_packet_ids:
            updated_packets.append(packet)
            continue
        candidates: list[ResearchCandidate] = []
        for candidate in packet.candidates:
            candidate_facts = [
                item
                for item in packet.fact_assertions
                if item.entity_ref.entity_id == candidate.candidate_id
            ]
            candidate = normalize_lodging_price_evidence(
                candidate,
                candidate_facts=candidate_facts,
                source_records=packet.source_records,
            )
            candidate_days = _weather_days(weather_snapshot, candidate)
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
            candidate = candidate.model_copy(
                update={
                    "weather_impact_ids": [
                        impact.weather_impact_id for impact in candidate_impacts
                    ]
                }
            )
            candidates.append(candidate)
            impacts.extend(candidate_impacts)
            scopes = list(
                dict.fromkeys(
                    previous_scopes_by_candidate.get(candidate.candidate_id, [])
                )
            ) or [None]
            for selection_slot_id in scopes:
                admissions.append(
                    admit_candidate(
                        candidate,
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
                            candidate.destination_id
                        ),
                        require_destination_country_scope=(
                            not allow_unanchored_existing_identity
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
                        source_records=packet.source_records,
                    )
                )
        updated_packets.append(packet.model_copy(update={"candidates": candidates}))

    refreshed_catalog = bundle.workspace.recommendation_catalog.model_copy(
        update={
            "generation_id": bundle.manifest.generation_id,
            "fact_data_revision": bundle.manifest.fact_data_revision,
            "weather_data_revision": bundle.manifest.weather_data_revision,
            "research_packets": updated_packets,
            "admission_results": admissions,
            "candidate_discovery_records": [
                record
                for packet in updated_packets
                for record in packet.candidate_discovery_records
            ],
            "candidate_ranking_scores": [],
        }
    )
    unique_impacts = {item.weather_impact_id: item for item in impacts}
    return CandidateCatalogReadmissionResult(
        candidate_ids=candidate_ids,
        catalog=refreshed_catalog,
        weather_impacts=tuple(unique_impacts.values()),
    )
