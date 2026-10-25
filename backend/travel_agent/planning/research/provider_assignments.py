"""Planning research provider assignments."""

from __future__ import annotations

from travel_agent.planning.requirements.route_legs import _identity_parts
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.provider_contracts import (
    ProviderEvidenceAssignment,
    ProviderEvidenceOutcome,
)
from travel_agent.planning.research.provider_contracts import (
    ProviderEvidenceCandidateKind,
)
from travel_agent.planning.research.provider_contracts import ProviderEvidenceScope
from travel_agent.planning.research.provider_contracts import (
    ProviderEvidenceTransportClass,
)
from travel_agent.planning.research.provider_contracts import ProviderEvidenceWorkerKind
from travel_agent.planning.research.provider_contracts import ProviderRouteLegScope
from travel_agent.planning.research.provider_scope_ids import provider_evidence_scope_id
from typing import Any
from typing import Iterable
from typing import Mapping
from typing import Optional
from typing import Sequence
from typing import cast


def scope_attempt_numbers(
    outcomes: Mapping[str, "ProviderEvidenceOutcome"],
) -> dict[str, int]:
    """The run's highest recorded attempt per Provider evidence scope."""
    return {
        scope_id: outcome.attempt_number
        for scope_id, outcome in (outcomes or {}).items()
    }


def build_provider_evidence_assignments(
    *,
    run_id: str,
    constraint_pack_revision: int,
    worker_kind: ProviderEvidenceWorkerKind,
    controlled_trip_identity: Mapping[str, Any],
    prior_scope_attempts: Mapping[str, int],
    candidate_kinds: Optional[Sequence[str]] = None,
    transport_classes: Optional[Sequence[str]] = None,
    long_distance_legs: Optional[Sequence[ProviderRouteLegScope]] = None,
) -> list[ProviderEvidenceAssignment]:
    """Build explicit business scopes; callers must persist them on assignment.

    ``prior_scope_attempts`` is the run's durable ``scope_id -> attempt_number``
    map, so each assignment is numbered **per scope**: one past this scope's own
    highest attempt, or ``0`` on its first.  The number must come from the scope
    and not from the caller's retry budget, because those are keyed differently —
    the targeted-research ledger is keyed per *product gap* while a local-transport
    scope covers the whole destination set.  Number it from the caller's budget and two
    connector rounds motivated by two different adjacencies both report "attempt 1" on
    the same scope with different option counts, at which point
    `merge_provider_evidence_outcomes` correctly refuses to merge them and
    `same Provider evidence attempt produced conflicting outcomes` kills the run.
    """

    origin_id, destination_ids = _identity_parts(controlled_trip_identity)
    destination_target = (
        f"destinations:{','.join(destination_ids)}"
        if destination_ids
        else f"run:{run_id}"
    )
    dimensions: list[
        tuple[
            ResearchDomain,
            Optional[ProviderEvidenceCandidateKind],
            Optional[ProviderEvidenceTransportClass],
            Optional[str],
            Optional[ProviderRouteLegScope],
        ]
    ] = []
    if worker_kind == "destination_researcher":
        kinds = ("visit", "dining") if candidate_kinds is None else candidate_kinds
        for raw_kind in dict.fromkeys(kinds):
            if raw_kind not in {"visit", "dining"}:
                raise ValueError(f"unsupported destination Provider scope: {raw_kind}")
            kind = cast(ProviderEvidenceCandidateKind, raw_kind)
            dimensions.append(
                (
                    ResearchDomain.VISIT if kind == "visit" else ResearchDomain.DINING,
                    kind,
                    None,
                    destination_target,
                    None,
                )
            )
    elif worker_kind == "accommodation_researcher":
        dimensions.append(
            (
                ResearchDomain.LODGING,
                "lodging",
                None,
                destination_target,
                None,
            )
        )
    else:
        classes = (
            ("long_distance", "public_transit", "flexible")
            if transport_classes is None
            else transport_classes
        )
        for raw_class in dict.fromkeys(classes):
            if raw_class not in {
                "long_distance",
                "public_transit",
                "flexible",
            }:
                raise ValueError(f"unsupported transport Provider scope: {raw_class}")
            transport_class = cast(
                ProviderEvidenceTransportClass,
                raw_class,
            )
            if transport_class == "long_distance":
                if not long_distance_legs:
                    raise ValueError(
                        "long-distance Provider scopes require exact route legs"
                    )
                dimensions.extend(
                    (
                        ResearchDomain.LONG_DISTANCE_TRANSPORT,
                        None,
                        transport_class,
                        None,
                        route_leg,
                    )
                    for route_leg in long_distance_legs
                )
            else:
                dimensions.append(
                    (
                        ResearchDomain.LOCAL_TRANSPORT,
                        None,
                        transport_class,
                        destination_target,
                        None,
                    )
                )
    assignments = []
    for (
        domain,
        candidate_kind,
        transport_class,
        target_identity,
        route_leg,
    ) in dimensions:
        scope_id = provider_evidence_scope_id(
            run_id=run_id,
            constraint_pack_revision=constraint_pack_revision,
            worker_kind=worker_kind,
            research_domain=domain,
            candidate_kind=candidate_kind,
            transport_class=transport_class,
            target_identity=target_identity,
            route_leg=route_leg,
        )
        assignments.append(
            ProviderEvidenceAssignment(
                scope=ProviderEvidenceScope(
                    scope_id=scope_id,
                    run_id=run_id,
                    constraint_pack_revision=constraint_pack_revision,
                    worker_kind=worker_kind,
                    research_domain=domain,
                    candidate_kind=candidate_kind,
                    transport_class=transport_class,
                    target_identity=target_identity,
                    route_leg=route_leg,
                ),
                attempt_number=prior_scope_attempts.get(scope_id, -1) + 1,
            )
        )
    return assignments


def parse_provider_evidence_assignments(
    assignment: Mapping[str, Any],
    *,
    expected_worker: ProviderEvidenceWorkerKind,
    expected_run_id: str,
    expected_constraint_pack_revision: int,
) -> list[ProviderEvidenceAssignment]:
    raw = assignment.get("provider_evidence_assignments")
    if not isinstance(raw, list) or not raw:
        raise ValueError("research assignment requires Provider evidence scopes")
    parsed = [ProviderEvidenceAssignment.model_validate(item) for item in raw]
    scope_ids = [item.scope.scope_id for item in parsed]
    if len(scope_ids) != len(set(scope_ids)):
        raise ValueError("Provider evidence assignment scopes must be unique")
    if any(
        item.scope.worker_kind != expected_worker
        or item.scope.run_id != expected_run_id
        or item.scope.constraint_pack_revision != expected_constraint_pack_revision
        for item in parsed
    ):
        raise ValueError("Provider evidence assignment authority mismatch")
    return parsed


def dump_provider_evidence_assignments(
    assignments: Iterable[ProviderEvidenceAssignment],
) -> list[dict[str, Any]]:
    return [assignment.model_dump(mode="json") for assignment in assignments]
