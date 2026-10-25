"""Planning delivery quality node."""

from __future__ import annotations

from typing import Any, Dict

from travel_agent.planning.delivery.quality.evaluation import (
    _attribution,
    evaluate_delivery_quality,
)
from travel_agent.planning.itinerary.revision import (
    apply_composition_repair_budget,
    composition_repair_attempts,
    composition_repair_budget_exhausted,
)
from travel_agent.planning.outcomes import (
    DeliveryContractViolation,
    GateClass,
    GateDisposition,
)
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.deadlines import observe_run_deadline

_RELEASED_SUBGATES = {
    "schema_gate": "passed",
    "candidate_gate": "passed",
    "slot_gate": "passed",
    "itinerary_gate": "passed",
    "source_weather_gate": "passed",
}


def _composition_window_closed(state: TravelAgentState) -> bool:
    """Whether the itinerary composition window has run out for this run."""
    if state.run_deadline is None:
        return False
    _observed, observation = observe_run_deadline(state.run_deadline)
    return observation.composition_closed


async def delivery_quality_gate_node(state: TravelAgentState) -> Dict[str, Any]:
    quality, gaps = evaluate_delivery_quality(state)
    blocking = [gap for gap in gaps if gap.blocking]
    update: Dict[str, Any] = {
        "recommendation_quality": quality,
        "delivery_quality_gaps": gaps,
    }
    if state.trip_workspace_v2 is None:
        if _composition_window_closed(state):
            raise DeliveryContractViolation(
                "composition window closed with no materialized workspace",
                reason_code="composition_window_exhausted",
                gate_class=GateClass.COMPOSITION,
            )
        if composition_repair_budget_exhausted(state):
            raise DeliveryContractViolation(
                "delivery quality gate reached with no materialized workspace",
                reason_code="composition_repair_budget_exhausted",
                gate_class=GateClass.COMPOSITION,
            )
        update.update(
            delivery_quality_route="composition_repair",
            composition_repair_attempts=composition_repair_attempts(state) + 1,
            gate_failure_attributions=_attribution(
                state,
                gate_class=GateClass.COMPOSITION,
                disposition=GateDisposition.COMPOSITION_REPAIR,
                reason_code="delivery_quality_workspace_unmaterialized",
                gaps=blocking,
            ),
        )
        return update
    if not blocking or composition_repair_budget_exhausted(state):
        update["recommendation_quality"] = quality.model_copy(update=_RELEASED_SUBGATES)
        update["delivery_quality_route"] = "passed"
        return update

    update.update(
        delivery_quality_route="composition_repair",
        gate_failure_attributions=_attribution(
            state,
            gate_class=GateClass.COMPOSITION,
            disposition=GateDisposition.COMPOSITION_REPAIR,
            reason_code="delivery_quality_composition_gap",
            gaps=blocking,
        ),
    )
    return apply_composition_repair_budget(
        state,
        update,
        route_key="delivery_quality_route",
        exhausted_route="passed",
    )


def route_after_delivery_quality_gate(state: TravelAgentState) -> str:
    """Route to projection unless the node granted a repair round out of budget."""

    if state.delivery_quality_route != "composition_repair":
        return "passed"
    deadline = state.run_deadline
    if deadline is None:
        return "composition_repair"
    _observed, observation = observe_run_deadline(deadline)
    if observation.composition_closed:
        return "passed"
    return "composition_repair"
