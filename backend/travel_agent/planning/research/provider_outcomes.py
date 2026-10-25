"""Planning research provider outcomes."""

from __future__ import annotations

from travel_agent.planning.research.provider_contracts import ProviderEvidenceOutcome
from travel_agent.planning.research.provider_contracts import ProviderEvidenceSummary
from typing import Dict
from typing import Mapping


def merge_provider_evidence_outcomes(
    a: Dict[str, ProviderEvidenceOutcome],
    b: Dict[str, ProviderEvidenceOutcome],
) -> Dict[str, ProviderEvidenceOutcome]:
    """Merge current outcomes by explicit attempt, independent of fan-in order."""

    merged = dict(a or {})
    for scope_id, incoming in (b or {}).items():
        if scope_id != incoming.scope.scope_id:
            raise ValueError("Provider evidence outcome map key mismatch")
        previous = merged.get(scope_id)
        if previous is None:
            merged[scope_id] = incoming
            continue
        if previous.scope != incoming.scope:
            raise ValueError("Provider evidence scope identity conflict")
        if previous.attempt_number == incoming.attempt_number:
            if previous != incoming:
                raise ValueError(
                    "same Provider evidence attempt produced conflicting outcomes"
                )
            continue
        newer, older = (
            (incoming, previous)
            if incoming.attempt_number > previous.attempt_number
            else (previous, incoming)
        )
        if newer.status == "no_option" and older.status == "unresolved_loss":
            newer = newer.model_copy(
                update={
                    "status": "unresolved_loss",
                    "unresolved_loss_count": older.unresolved_loss_count,
                }
            )
        merged[scope_id] = newer
    return merged


def current_provider_evidence_summary(
    outcomes: Mapping[str, ProviderEvidenceOutcome],
    *,
    constraint_pack_revision: int,
) -> ProviderEvidenceSummary:
    current = [
        outcome
        for outcome in outcomes.values()
        if outcome.scope.constraint_pack_revision == constraint_pack_revision
    ]
    unresolved = [outcome for outcome in current if outcome.status == "unresolved_loss"]
    return ProviderEvidenceSummary(
        current_scope_count=len(current),
        unresolved_scope_count=len(unresolved),
        provider_option_count=sum(outcome.provider_option_count for outcome in current),
        provider_option_materialized_count=sum(
            outcome.provider_option_materialized_count for outcome in current
        ),
        provider_salvage_loss_count=sum(
            outcome.unresolved_loss_count for outcome in unresolved
        ),
    )
