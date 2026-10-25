from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Dict, Iterable

from travel_agent.entities.state import TravelAgentState
from travel_agent.planning.outcomes import (
    GateClass,
    GateDisposition,
    GateFailureAttribution,
)
from travel_agent.planning.research.domains import ResearchDomain


def _stable_attribution_id(
    *,
    draft_id: str | None,
    gate_class: GateClass,
    disposition: GateDisposition,
    reason_code: str,
    domain: ResearchDomain | None,
    gap_ids: Iterable[str],
    failure_signature: str | None,
) -> str:
    material = "|".join(
        [
            draft_id or "",
            gate_class.value,
            disposition.value,
            reason_code,
            domain.value if domain else "",
            ",".join(sorted(set(gap_ids))),
            failure_signature or "",
        ]
    )
    return f"gate_failure_{hashlib.sha256(material.encode()).hexdigest()[:24]}"


def _record_attribution(
    state: TravelAgentState,
    *,
    gate_class: GateClass,
    disposition: GateDisposition,
    reason_code: str,
    domain: ResearchDomain | None = None,
    gap_ids: Iterable[str] = (),
    failure_signature: str | None = None,
    deterministic: bool = False,
    retry_attempt: int = 0,
) -> Dict[str, GateFailureAttribution]:
    ids = list(dict.fromkeys(gap_ids))
    draft_id = (
        state.minimum_delivery_draft.draft_id if state.minimum_delivery_draft else None
    )
    attribution = GateFailureAttribution(
        attribution_id=_stable_attribution_id(
            draft_id=draft_id,
            gate_class=gate_class,
            disposition=disposition,
            reason_code=reason_code,
            domain=domain,
            gap_ids=ids,
            failure_signature=failure_signature,
        ),
        gate_class=gate_class,
        disposition=disposition,
        reason_code=reason_code,
        draft_id=draft_id,
        research_domain=domain,
        gap_ids=ids,
        failure_signature=failure_signature,
        deterministic=deterministic,
        retry_attempt=retry_attempt,
        recorded_at=datetime.now(timezone.utc),
    )
    records = dict(state.gate_failure_attributions or {})
    records[attribution.attribution_id] = attribution
    return records
