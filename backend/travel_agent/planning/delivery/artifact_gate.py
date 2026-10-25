"""Planning delivery artifact gate."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict

from pydantic import ValidationError

from travel_agent.planning.assignments import strip_round_suffix
from travel_agent.planning.itinerary.revision import apply_composition_repair_budget
from travel_agent.planning.nodes import RESEARCH_WORKER_NODES as _RESEARCH_WORKERS
from travel_agent.planning.outcomes import (
    GateClass,
    GateDisposition,
    GateFailureAttribution,
)
from travel_agent.planning.research.history import _latest_packets
from travel_agent.planning.research.provider_failure import (
    classify_provider_failure,
    is_provider_or_model_failure,
)
from travel_agent.planning.research.retry import (
    worker_research_satisfied_by_a_later_round,
    worker_targeted_research_exhausted,
)
from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.workspace import TripWorkspaceV2
from travel_agent.runtime.deadlines import observe_run_deadline


def _round_trip_workspace(workspace: Any) -> TripWorkspaceV2 | None:
    """Return only a freshly schema-validated workspace artifact."""

    if not isinstance(workspace, TripWorkspaceV2):
        return None
    try:
        return TripWorkspaceV2.model_validate(workspace.model_dump(mode="python"))
    except (ValidationError, TypeError, ValueError, AttributeError):
        return None


def _planned_agent_keys(state: TravelAgentState) -> list[str]:
    return [agent for group in state.execution_plan or [] for agent in group]


def _current_research_packet(
    state: TravelAgentState,
    agent_key: str,
):
    """Resolve a worker packet through its generation-qualified state key."""

    if state.planning_generation is None:
        return None
    return _latest_packets(
        state.research_packets or {},
        generation_id=state.planning_generation.generation_id,
    ).get(strip_round_suffix(agent_key))


def _attribution(
    state: TravelAgentState,
    *,
    gate_class: GateClass,
    disposition: GateDisposition,
    reason_code: str,
    gap_id: str,
    deterministic: bool = False,
) -> Dict[str, GateFailureAttribution]:
    draft_id = (
        state.minimum_delivery_draft.draft_id if state.minimum_delivery_draft else None
    )
    material = "|".join(
        [
            draft_id or "",
            gate_class.value,
            disposition.value,
            reason_code,
            gap_id,
        ]
    )
    attribution_id = (
        f"gate_failure_{hashlib.sha256(material.encode()).hexdigest()[:24]}"
    )
    records = dict(state.gate_failure_attributions or {})
    records[attribution_id] = GateFailureAttribution(
        attribution_id=attribution_id,
        gate_class=gate_class,
        disposition=disposition,
        reason_code=reason_code,
        draft_id=draft_id,
        gap_ids=[gap_id],
        deterministic=deterministic,
        recorded_at=datetime.now(timezone.utc),
    )
    return records


def _integrity_result(
    state: TravelAgentState,
    *,
    agent_key: str,
    reason_code: str,
    message: str,
) -> Dict[str, Any]:
    """Record a typed-artifact gap and hand the run to the delivery quality gate."""
    return {
        "artifact_gate_route": "accepted",
        "artifact_status": {agent_key: "integrity_failed"},
        "gate_failure_attributions": _attribution(
            state,
            gate_class=GateClass.COMPOSITION,
            disposition=GateDisposition.COMPOSITION_REPAIR,
            reason_code=reason_code,
            gap_id=f"artifact:{agent_key}:{reason_code}",
        ),
        "last_error": message,
    }


def _content_failure_result(
    state: TravelAgentState,
    *,
    agent_key: str,
    reason_code: str,
    deterministic: bool,
) -> Dict[str, Any]:
    """Hand one worker's content failure to the owner of the research budget."""
    exhausted = worker_targeted_research_exhausted(state, strip_round_suffix(agent_key))
    satisfied_by_retry = exhausted and worker_research_satisfied_by_a_later_round(
        state, agent_key
    )
    return {
        "artifact_gate_route": "accepted" if exhausted else "candidate_gate",
        "artifact_status": {agent_key: "content_gap"},
        "gate_failure_attributions": _attribution(
            state,
            gate_class=GateClass.COMPOSITION,
            disposition=(
                GateDisposition.RESEARCH_EXHAUSTED
                if exhausted
                else GateDisposition.TARGETED_RESEARCH
            ),
            reason_code=(
                "research_satisfied_by_scoped_retry"
                if satisfied_by_retry
                else reason_code
            ),
            gap_id=f"artifact:{agent_key}:content_failure",
            deterministic=deterministic,
        ),
    }


async def artifact_gate_node(state: TravelAgentState) -> Dict[str, Any]:
    """Validate typed artifacts without turning content gaps into run failures."""
    for agent_key in _planned_agent_keys(state):
        base = strip_round_suffix(agent_key)
        if base not in _RESEARCH_WORKERS and base != "itinerary_planner":
            continue
        status = str((state.agent_status or {}).get(agent_key) or "")

        if base in _RESEARCH_WORKERS:
            packet = _current_research_packet(state, agent_key)
            if packet is not None:
                if packet.worker_kind != base or packet.run_id != state.run_id:
                    return _integrity_result(
                        state,
                        agent_key=agent_key,
                        reason_code="research_packet_identity_invalid",
                        message=f"research packet identity does not match {agent_key}",
                    )
                if status in {"completed", "partial"}:
                    continue

                if status == "failed" or status not in {"completed", "partial"}:
                    if is_provider_or_model_failure(state.last_error):
                        classification = classify_provider_failure(state.last_error)
                        reason_code = classification.reason_code
                        deterministic = classification.category == "deterministic"
                    else:
                        reason_code = "research_packet_present_but_worker_failed"
                        deterministic = False
                    return _content_failure_result(
                        state,
                        agent_key=agent_key,
                        reason_code=reason_code,
                        deterministic=deterministic,
                    )
            if status == "failed" and is_provider_or_model_failure(state.last_error):
                classification = classify_provider_failure(state.last_error)
                return _content_failure_result(
                    state,
                    agent_key=agent_key,
                    reason_code=classification.reason_code,
                    deterministic=classification.category == "deterministic",
                )
            return _integrity_result(
                state,
                agent_key=agent_key,
                reason_code="required_research_packet_missing",
                message=(
                    f"required typed research packet is absent or malformed: "
                    f"agent={agent_key}, status={status or 'missing'}"
                ),
            )

        if status == "failed" and is_provider_or_model_failure(state.last_error):
            classification = classify_provider_failure(state.last_error)
            return apply_composition_repair_budget(
                state,
                {
                    "artifact_gate_route": "composition_repair",
                    "artifact_status": {agent_key: "composition_gap"},
                    "gate_failure_attributions": _attribution(
                        state,
                        gate_class=GateClass.COMPOSITION,
                        disposition=GateDisposition.COMPOSITION_REPAIR,
                        reason_code="itinerary_provider_or_model_failure",
                        gap_id=f"artifact:{agent_key}:{classification.reason_code}",
                        deterministic=classification.category == "deterministic",
                    ),
                },
                route_key="artifact_gate_route",
                exhausted_route="accepted",
            )

        workspace = _round_trip_workspace(state.trip_workspace_v2)
        if (
            status in {"completed", "partial"}
            and workspace is not None
            and workspace.run_id == state.run_id
            and state.recommendation_catalog is not None
            and workspace.recommendation_catalog == state.recommendation_catalog
            and workspace.itinerary.day_plans
        ):
            continue
        return _integrity_result(
            state,
            agent_key=agent_key,
            reason_code="required_workspace_artifact_missing",
            message=(
                f"required typed workspace artifact is absent or malformed: "
                f"agent={agent_key}, status={status or 'missing'}"
            ),
        )

    return {
        "artifact_gate_route": "accepted",
        "artifact_status": {key: "accepted" for key in _planned_agent_keys(state)},
    }


def route_after_artifact_gate(state: TravelAgentState) -> str:
    route = state.artifact_gate_route or "accepted"
    deadline = state.run_deadline
    if deadline is None:
        return route
    _observed, observation = observe_run_deadline(deadline)
    if observation.research_closed:
        return "accepted"
    return route
