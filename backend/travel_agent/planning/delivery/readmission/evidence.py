"""Planning delivery readmission evidence."""

from __future__ import annotations

from datetime import datetime
from pydantic import ValidationError
from travel_agent.planning.delivery.bundle import DeliveryBundle
from travel_agent.planning.delivery.readmission.contracts import (
    CandidateReadmissionError,
)
from travel_agent.planning.delivery.readmission_freshness import _aware
from travel_agent.planning.delivery.readmission_freshness import _fact_is_current_as_of
from travel_agent.planning.delivery.readmission_freshness import _freshness_status
from travel_agent.planning.requirements.constraint_applicability import (
    build_candidate_constraint_gate_attestation,
)
from travel_agent.planning.research.candidates import CandidateConstraintEvaluation
from travel_agent.planning.research.candidates import ResearchCandidate
from travel_agent.planning.research.evidence import FactAssertion
from travel_agent.planning.research.evidence import FieldProvenance
from travel_agent.planning.research.evidence import SourceRecord
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.planning.workspace import TripWorkspaceV2
from typing import Mapping
from typing import Sequence


def workspace_hard_constraint_pack(
    workspace: TripWorkspaceV2,
) -> dict[str, list[dict[str, object]]]:
    """Reconstruct only durable, active hard constraints from Workspace anchors.

    A post-delivery re-admission has no access to volatile LangGraph state.
    Its current Workspace anchors are therefore the only authoritative source
    for user-owned hard constraints; omitting them would make a new admission
    silently less strict than the Bundle that produced the itinerary.
    """

    constraints: list[dict[str, object]] = []
    for anchor in workspace.user_input_anchors:
        if anchor.input_kind != "hard_constraint" or not anchor.constraint_id:
            continue
        if isinstance(anchor.value, Mapping):
            item = {str(key): value for key, value in anchor.value.items()}
        else:
            item = {"value": anchor.value}
        item["constraint_id"] = anchor.constraint_id

        item["status"] = "active"
        item.setdefault("category", anchor.field_path)
        constraints.append(item)
    return {"hard_constraints": constraints}


def workspace_destination_country_codes(workspace: TripWorkspaceV2) -> dict[str, str]:
    """Read only controlled destination identity anchors for re-admission."""

    result: dict[str, str] = {}

    def add(value: object) -> None:
        if not isinstance(value, Mapping):
            return
        place_id = value.get("place_id") or value.get("destination_id")
        country_code = value.get("country_code")
        if place_id and country_code:
            result[str(place_id)] = str(country_code)
        destinations = value.get("destinations")
        if isinstance(destinations, list):
            for destination in destinations:
                add(destination)

    for anchor in workspace.user_input_anchors:
        if "destination" in anchor.field_path or anchor.field_path in {
            "controlled_trip_identity",
            "controlled_identity",
        }:
            add(anchor.value)
    return result


def _assert_catalog_is_not_future(bundle: DeliveryBundle) -> None:
    catalog = bundle.workspace.recommendation_catalog
    if catalog.fact_data_revision > bundle.manifest.fact_data_revision:
        raise CandidateReadmissionError(
            "candidate_catalog_future_revision",
            "Recommendation Catalog uses a future fact revision",
        )
    if catalog.weather_data_revision > bundle.manifest.weather_data_revision:
        raise CandidateReadmissionError(
            "candidate_catalog_future_revision",
            "Recommendation Catalog uses a future weather revision",
        )
    packet_revisions = {
        packet.constraint_pack_revision for packet in catalog.research_packets
    }
    if len(packet_revisions) > 1:
        raise CandidateReadmissionError(
            "candidate_constraint_revision_inconsistent",
            "Candidate packets use inconsistent constraint revisions",
        )


def _rebind_constraint_evaluations(
    candidate: ResearchCandidate,
    *,
    packet: ResearchPacket,
    candidate_facts: Sequence[FactAssertion],
    candidate_sources: Sequence[SourceRecord],
    fact_data_revision: int,
    constraint_pack: Mapping[str, object] | None,
    expected_active_constraint_ids: Sequence[str],
    allow_fact_revision_rebind: bool = False,
) -> ResearchCandidate:
    """Keep a verdict only when Candidate Gate attested its exact inputs.

    Historical model verdicts are never sufficient.  The typed attestation
    binds the candidate's fact tuple, scoped semantic constraint payload,
    evaluation tuple, run/packet identity and current Fact revision.  A
    weather-only atomic refresh may carry the same verdict over a new global
    fact revision, but only when every other proof component still matches.
    """

    scoped_ids = tuple(expected_active_constraint_ids)
    if not scoped_ids:
        return candidate.model_copy(
            update={
                "active_constraint_ids": [],
                "constraint_evaluations": [],
                "constraint_gate_attestation": None,
            }
        )
    attestation_packet = packet.model_copy(
        update={
            "fact_data_revision": fact_data_revision,
            "fact_assertions": list(candidate_facts),
            "source_records": list(candidate_sources),
            "candidates": [candidate],
        }
    )
    expected = build_candidate_constraint_gate_attestation(
        attestation_packet,
        candidate,
        constraint_pack=constraint_pack,
        fact_data_revision=fact_data_revision,
    )
    actual = candidate.constraint_gate_attestation
    exact = actual == expected
    same_proof_except_revision = (
        actual is not None
        and expected is not None
        and actual.schema_version == expected.schema_version
        and actual.run_id == expected.run_id
        and actual.research_packet_id == expected.research_packet_id
        and actual.worker_kind == expected.worker_kind
        and actual.candidate_id == expected.candidate_id
        and actual.scoped_constraint_fingerprint
        == expected.scoped_constraint_fingerprint
        and actual.candidate_facts_fingerprint == expected.candidate_facts_fingerprint
        and actual.evaluation_fingerprint == expected.evaluation_fingerprint
    )
    if (
        expected is not None
        and tuple(candidate.active_constraint_ids) == scoped_ids
        and (exact or (allow_fact_revision_rebind and same_proof_except_revision))
    ):
        return candidate.model_copy(
            update={
                "active_constraint_ids": list(scoped_ids),
                "constraint_gate_attestation": expected,
            }
        )

    rebound = [
        CandidateConstraintEvaluation(
            constraint_id=constraint_id,
            status="unknown",
            fact_assertion_ids=[],
            reason_code="current_constraint_evaluation_required",
        )
        for constraint_id in expected_active_constraint_ids
    ]
    return candidate.model_copy(
        update={
            "active_constraint_ids": list(scoped_ids),
            "constraint_evaluations": rebound,
            "constraint_gate_attestation": None,
        }
    )


def _current_packet(
    packet: ResearchPacket,
    *,
    fact_data_revision: int,
    fact_index: Mapping[str, FactAssertion],
    source_index: Mapping[str, SourceRecord],
    field_provenance: Sequence[FieldProvenance],
    source_order: Sequence[str],
    provenance_order: Mapping[int, int],
    constraint_pack: Mapping[str, object] | None,
    expected_active_constraint_ids: Sequence[str],
    as_of: datetime,
    allow_fact_revision_rebind: bool = False,
) -> ResearchPacket:
    """Rebind one immutable packet only to facts in the current snapshot."""

    if not packet.candidates:
        return packet.model_copy(update={"fact_data_revision": fact_data_revision})
    candidate_fact_ids: list[str] = []
    candidate_ids = {candidate.candidate_id for candidate in packet.candidates}
    for candidate in packet.candidates:
        for fact_id in candidate.fact_assertion_ids:
            if fact_id not in candidate_fact_ids:
                candidate_fact_ids.append(fact_id)

    missing_fact_ids = [
        fact_id for fact_id in candidate_fact_ids if fact_id not in fact_index
    ]
    if missing_fact_ids:
        raise CandidateReadmissionError(
            "candidate_evidence_missing",
            "Current FactStore no longer contains Candidate evidence",
        )
    facts: list[FactAssertion] = []
    invalidated_current_fact = False
    for fact_id in candidate_fact_ids:
        fact = fact_index[fact_id]
        if fact.status == "verified" and not _fact_is_current_as_of(
            fact, sources=source_index, as_of=as_of
        ):
            facts.append(fact.model_copy(update={"status": "stale"}))
            invalidated_current_fact = True
        else:
            facts.append(fact)
    if any(fact.entity_ref.entity_id not in candidate_ids for fact in facts):
        raise CandidateReadmissionError(
            "candidate_evidence_inconsistent",
            "Current Candidate facts no longer match their packet identities",
        )

    source_ids = {link.source_record_id for fact in facts for link in fact.source_links}
    if not source_ids or any(source_id not in source_index for source_id in source_ids):
        raise CandidateReadmissionError(
            "candidate_evidence_missing",
            "Current FactStore no longer contains Candidate sources",
        )
    sources = [
        source_index[source_id] for source_id in source_order if source_id in source_ids
    ]

    fact_pairs = {(fact.entity_ref.entity_id, fact.field_path) for fact in facts}
    current_provenance = [
        item
        for item in field_provenance
        if (item.entity_ref.entity_id, item.field_path) in fact_pairs
        and (
            item.origin != "external_fact"
            or set(item.reference_ids) <= set(candidate_fact_ids)
        )
    ]
    current_provenance.sort(key=lambda item: provenance_order[id(item)])
    provenance_pairs = {
        (item.entity_ref.entity_id, item.field_path) for item in current_provenance
    }
    if not fact_pairs <= provenance_pairs:
        raise CandidateReadmissionError(
            "candidate_evidence_missing",
            "Current FactStore lacks Candidate field provenance",
        )

    facts_by_candidate: dict[str, list[FactAssertion]] = {}
    for fact in facts:
        facts_by_candidate.setdefault(fact.entity_ref.entity_id, []).append(fact)
    candidates = []
    for candidate in packet.candidates:
        current_candidate = candidate.model_copy(
            update={
                "freshness_status": _freshness_status(
                    facts_by_candidate[candidate.candidate_id]
                )
            }
        )
        candidates.append(
            _rebind_constraint_evaluations(
                current_candidate,
                packet=packet,
                candidate_facts=facts_by_candidate[candidate.candidate_id],
                candidate_sources=[
                    source
                    for source in sources
                    if source.source_record_id in candidate.source_record_ids
                ],
                fact_data_revision=fact_data_revision,
                constraint_pack=constraint_pack,
                expected_active_constraint_ids=expected_active_constraint_ids,
                allow_fact_revision_rebind=allow_fact_revision_rebind,
            )
        )
    try:
        return ResearchPacket.model_validate(
            {
                **packet.model_dump(mode="python"),
                "fact_data_revision": fact_data_revision,
                "candidates": candidates,
                "source_records": sources,
                "fact_assertions": facts,
                "field_provenance": current_provenance,
                "generated_at": _aware(as_of)
                if invalidated_current_fact
                else packet.generated_at,
            }
        )
    except ValidationError as exc:
        raise CandidateReadmissionError(
            "candidate_snapshot_inconsistent",
            "Current FactStore evidence cannot safely re-admit the Candidate packet",
        ) from exc
