from __future__ import annotations

from travel_agent.planning.research.provider_contracts import ProviderEvidenceOutcome
from typing import Dict


def merge_provider_evidence_outcomes(
    a: Dict[str, ProviderEvidenceOutcome],
    b: Dict[str, ProviderEvidenceOutcome],
) -> Dict[str, ProviderEvidenceOutcome]:
    """按显式尝试序号合并当前结果，合并结果与到达顺序无关。"""

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
