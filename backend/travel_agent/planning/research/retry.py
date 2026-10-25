from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable

from travel_agent.planning.requirements.route_legs import build_required_long_distance_legs
from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.assignments import strip_round_suffix
from travel_agent.planning.outcomes import (
    CandidateResearchGap,
    GateClass,
    GateDisposition,
)
from travel_agent.planning.research.attribution import _record_attribution
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.failure_signals import (
    ProviderFailureSignal,
    _worker_failure_signals,
)
from travel_agent.planning.research.history import _latest_packets

_MAX_TARGETED_RESEARCH_ATTEMPTS = 1


_COMPANION_PACKED_FIELD_PATH = "transport_class.long_distance"


def _worker_retry_scope_prefix(worker_kind: str) -> str:
    """The ledger-key prefix every gap scope of one worker shares."""
    return f"{worker_kind}|gap|"


def _retry_scope_for_gap(
    gap: CandidateResearchGap,
) -> str:
    """Return the retry ledger key for one product gap, never a whole worker."""
    material = "|".join(
        [
            gap.worker_kind,
            gap.gap_id,
            gap.field_path or "",
            gap.candidate_id or "",
            gap.research_domain.value if gap.research_domain else "",
        ]
    )
    digest = hashlib.sha256(material.encode()).hexdigest()[:12]
    domain = gap.research_domain.value if gap.research_domain else "visit"
    return f"{_worker_retry_scope_prefix(gap.worker_kind)}{digest}|domain:{domain}"


def _worker_targeted_research_call_spent(
    state: TravelAgentState,
    worker_kind: str,
) -> bool:
    """Whether the durable ledger already records a targeted call for a worker."""
    prefix = _worker_retry_scope_prefix(worker_kind)
    return any(
        scope.startswith(prefix) and int(count) >= _MAX_TARGETED_RESEARCH_ATTEMPTS
        for scope, count in (state.candidate_gate_attempts or {}).items()
    )


def _domain_research_budget(
    state: TravelAgentState,
    domain: ResearchDomain,
) -> int:
    """Limit calls by the domain's fixed research responsibilities."""

    identity = state.controlled_trip_identity or {}
    if not isinstance(identity, dict):
        return _MAX_TARGETED_RESEARCH_ATTEMPTS
    if domain is ResearchDomain.LONG_DISTANCE_TRANSPORT:
        legs = build_required_long_distance_legs(
            identity, cross_day_return_required=False
        )
        return max(len(legs), _MAX_TARGETED_RESEARCH_ATTEMPTS)
    if domain is ResearchDomain.VISIT:
        destinations = [
            item
            for item in (identity.get("destinations") or ())
            if isinstance(item, dict) and str(item.get("place_id") or "").strip()
        ]
        return max(len(destinations), _MAX_TARGETED_RESEARCH_ATTEMPTS)
    if domain is ResearchDomain.LOCAL_TRANSPORT:
        return max(
            len(state.local_connector_gaps or ()), _MAX_TARGETED_RESEARCH_ATTEMPTS
        )
    return _MAX_TARGETED_RESEARCH_ATTEMPTS


def _gap_research_exhausted(
    state: TravelAgentState,
    *,
    gap: CandidateResearchGap,
) -> bool:
    if gap.status == "exhausted":
        return True
    domain = gap.research_domain or ResearchDomain.VISIT
    attempts = state.candidate_gate_attempts or {}
    domain_marker = f"|domain:{domain.value}"
    domain_spent = sum(
        int(count) for scope, count in attempts.items() if domain_marker in scope
    )
    if domain_spent >= _domain_research_budget(state, domain):
        return True
    if gap.field_path == _COMPANION_PACKED_FIELD_PATH:
        # One attempt covers companion legs together, so only their domain total applies.
        return False
    return (
        int(attempts.get(_retry_scope_for_gap(gap), 0))
        >= _MAX_TARGETED_RESEARCH_ATTEMPTS
    )


def _research_gap_priority(gap: CandidateResearchGap) -> int:
    if gap.intent_id:
        return 0
    field_path = gap.field_path or ""
    if field_path.startswith(
        (
            "candidate_kind.",
            "transport_class.",
            "itinerary.connector.",
        )
    ):
        return 0
    if gap.candidate_id:
        return 1
    if field_path.startswith("itinerary."):
        return 2
    return 3


def _ordered_research_gaps(
    gaps: Iterable[CandidateResearchGap],
    blocked_workers: Iterable[str],
) -> list[CandidateResearchGap]:
    """Order repair targets deterministically without letting summary gaps win."""
    ordered: list[CandidateResearchGap] = []
    for worker in sorted(set(blocked_workers)):
        worker_gaps = [gap for gap in gaps if gap.worker_kind == worker]
        scoped = [gap for gap in worker_gaps if _research_gap_priority(gap) < 3]
        candidates = scoped or worker_gaps
        ordered.extend(
            sorted(
                candidates,
                key=lambda gap: (
                    _research_gap_priority(gap),
                    gap.research_domain.value if gap.research_domain else "",
                    gap.gap_id,
                ),
            )
        )
    return ordered


def _select_research_gap(
    state: TravelAgentState,
    *,
    gaps: Iterable[CandidateResearchGap],
    blocked_workers: Iterable[str],
    excluded_domains: Iterable[ResearchDomain] = (),
) -> CandidateResearchGap | None:
    """Return the next gap that still has a targeted research attempt left."""
    unavailable_domains = set(excluded_domains)
    return next(
        (
            gap
            for gap in _ordered_research_gaps(gaps, blocked_workers)
            if (gap.research_domain or ResearchDomain.VISIT) not in unavailable_domains
            and gap.status not in {"exhausted", "resolved"}
            and not _gap_research_exhausted(state, gap=gap)
        ),
        None,
    )


def worker_targeted_research_exhausted(
    state: TravelAgentState,
    worker_kind: str,
) -> bool:
    """Whether this gate would still spend a targeted research call on a worker."""
    worker_gaps = [
        gap for gap in state.candidate_research_gaps if gap.worker_kind == worker_kind
    ]
    if not worker_gaps:
        return _worker_targeted_research_call_spent(state, worker_kind)
    return (
        _select_research_gap(
            state,
            gaps=worker_gaps,
            blocked_workers=[worker_kind],
        )
        is None
    )


def worker_research_satisfied_by_a_later_round(
    state: TravelAgentState,
    agent_key: str,
) -> bool:
    """Whether a round after ``agent_key`` already answered for the same worker."""
    packets = state.research_packets or {}
    if state.planning_generation is None:
        return False
    latest = _latest_packets(
        packets,
        generation_id=state.planning_generation.generation_id,
    ).get(strip_round_suffix(agent_key))
    if latest is None:
        return False
    statuses = state.agent_status or {}
    return any(
        key != agent_key
        and packet is latest
        and statuses.get(key) in {"completed", "partial"}
        for key, packet in packets.items()
    )


def _mark_scoped_gaps_exhausted(
    gaps: Iterable[CandidateResearchGap],
    *,
    gap_ids: Iterable[str],
    signatures: Iterable[str],
) -> list[CandidateResearchGap]:
    selected_ids = set(gap_ids)
    normalized_signatures = list(dict.fromkeys(signatures))
    return [
        gap.model_copy(
            update={
                "status": "exhausted",
                "attempted_signatures": list(
                    dict.fromkeys([*gap.attempted_signatures, *normalized_signatures])
                ),
            }
        )
        if gap.gap_id in selected_ids and gap.status != "resolved"
        else gap
        for gap in gaps
    ]


def _resolve_research_target(
    state: TravelAgentState,
    *,
    gaps: list[CandidateResearchGap],
    blocked_workers: Iterable[str],
    packets_by_worker: Dict[str, Any],
    attributions: Dict[str, Any],
    failure_ledger: Dict[str, list[str]],
) -> tuple[
    CandidateResearchGap | None,
    list[CandidateResearchGap],
    Dict[str, Any],
    Dict[str, list[str]],
    list[ProviderFailureSignal],
]:
    """Choose an actionable gap after closing deterministic provider failures."""
    excluded_domains: set[ResearchDomain] = set()
    while True:
        primary_gap = _select_research_gap(
            state,
            gaps=gaps,
            blocked_workers=blocked_workers,
            excluded_domains=excluded_domains,
        )
        if primary_gap is None:
            return None, gaps, attributions, failure_ledger, []
        signals = _worker_failure_signals(
            state,
            packet=packets_by_worker.get(primary_gap.worker_kind),
            worker=primary_gap.worker_kind,
        )
        deterministic_signal = next(
            (signal for signal in signals if signal.category == "deterministic"),
            None,
        )
        if deterministic_signal is None:
            return primary_gap, gaps, attributions, failure_ledger, signals
        gap_domain = primary_gap.research_domain or ResearchDomain.VISIT
        gaps = _mark_scoped_gaps_exhausted(
            gaps,
            gap_ids=[primary_gap.gap_id],
            signatures=[deterministic_signal.signature],
        )
        deterministic_scope = _retry_scope_for_gap(primary_gap)
        failure_ledger[deterministic_scope] = list(
            dict.fromkeys(
                [
                    *failure_ledger.get(deterministic_scope, []),
                    *(signal.signature for signal in signals),
                ]
            )
        )
        attributions = _record_attribution(
            state.model_copy(update={"gate_failure_attributions": attributions}),
            gate_class=GateClass.COMPOSITION,
            disposition=GateDisposition.TARGETED_RESEARCH,
            reason_code=deterministic_signal.reason_code,
            domain=gap_domain,
            gap_ids=[primary_gap.gap_id],
            failure_signature=deterministic_signal.signature,
            deterministic=True,
        )
        excluded_domains.add(gap_domain)
