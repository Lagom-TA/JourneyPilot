from __future__ import annotations

from typing import Any, Dict

from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.itinerary.revision import bounded_repair_context
from travel_agent.planning.itinerary.draft import ItineraryCompositionError
from travel_agent.planning.itinerary.revision import apply_composition_repair_budget
from travel_agent.planning.outcomes import (
    CandidateResearchGap,
    GateClass,
    GateDisposition,
)
from travel_agent.planning.research.attribution import _record_attribution
from travel_agent.planning.research.retry import _mark_scoped_gaps_exhausted


def _placement_skeleton_verdict(exc: ItineraryCompositionError) -> str:
    """Bound the connector-extraction error passed to itinerary revision."""
    return bounded_repair_context(
        "placement_skeleton/connector_extraction",
        f"{type(exc).__name__}: {exc}",
    )


def _composition_repair_update(
    state: TravelAgentState,
    update: Dict[str, Any],
) -> Dict[str, Any]:
    """Spend the existing bounded composition budget, or release the catalog."""

    out = apply_composition_repair_budget(
        state,
        update,
        route_key="candidate_gate_route",
        exhausted_route="passed",
    )
    if out["candidate_gate_route"] == "passed":
        out["candidate_gate_status"] = "passed"
    return out


def _passed_update(
    state: TravelAgentState,
    *,
    base_update: Dict[str, Any],
    gaps: list[CandidateResearchGap],
    deadline: Any | None = None,
) -> Dict[str, Any]:
    """Hand the current catalog to composition and close remaining targets."""
    update = {
        **base_update,
        "candidate_research_gaps": _mark_scoped_gaps_exhausted(
            gaps,
            gap_ids=[gap.gap_id for gap in gaps if gap.status != "resolved"],
            signatures=(),
        ),
        "candidate_gate_status": "passed",
        "candidate_gate_route": "passed",
        "candidate_gate_attempts": dict(state.candidate_gate_attempts or {}),
    }
    if deadline is not None:
        update["run_deadline"] = deadline
    return update


def _catalog_contract_update(
    state: TravelAgentState,
    *,
    reason_code: str,
    message: str,
    worker_kind: str | None = None,
    base_update: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Record a catalog contract outcome and hand the run to composition."""
    accumulated = dict(base_update or {})
    gap_ids = (
        [f"catalog:{worker_kind}:{reason_code}"]
        if worker_kind
        else [f"catalog:{reason_code}"]
    )
    return {
        **accumulated,
        "candidate_gate_status": "passed",
        "candidate_gate_route": "passed",
        "gate_failure_attributions": _record_attribution(
            state.model_copy(
                update={
                    "gate_failure_attributions": accumulated.get(
                        "gate_failure_attributions",
                        state.gate_failure_attributions,
                    )
                }
            ),
            gate_class=GateClass.COMPOSITION,
            disposition=GateDisposition.COMPOSITION_REPAIR,
            reason_code=reason_code,
            gap_ids=gap_ids,
        ),
        "last_error": message,
    }
