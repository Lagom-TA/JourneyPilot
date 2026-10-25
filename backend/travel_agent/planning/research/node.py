from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Optional

from langchain_core.runnables import RunnableConfig

from travel_agent.entities.state import TravelAgentState
from travel_agent.planning.assignments import strip_round_suffix
from travel_agent.planning.execution import is_structural_connector_round
from travel_agent.planning.itinerary.connectors import (
    LocalConnectorGap,
    connector_candidate_quality_error,
    connector_mode_requests_from_constraint_pack,
    extract_local_connector_gaps,
)
from travel_agent.planning.itinerary.draft import ItineraryCompositionError
from travel_agent.planning.outcomes import (
    CandidateResearchGap,
    GateClass,
    GateDisposition,
)
from travel_agent.planning.research.assembly import build_candidate_catalog
from travel_agent.planning.research.attribution import _record_attribution
from travel_agent.planning.research.candidates import TransportCandidate
from travel_agent.planning.research.catalog import CandidateGateIntegrityError
from travel_agent.planning.research.deadlines import (
    _observe_deadline,
    _research_closeout_can_skip_connector_pass,
)
from travel_agent.planning.research.evaluation import evaluate_catalog
from travel_agent.planning.research.gaps import (
    _classify_candidate_gaps,
    _destination_coverage_gaps,
    _gap_id,
    _intent_research_gaps,
    _long_distance_gaps,
)
from travel_agent.planning.research.requirements import (
    _required_candidate_kinds,
    _required_workers,
)
from travel_agent.planning.research.retry import _resolve_research_target
from travel_agent.planning.research.scheduling import schedule_targeted_research
from travel_agent.planning.research.transitions import (
    _catalog_contract_update,
    _composition_repair_update,
    _passed_update,
    _placement_skeleton_verdict,
)
from travel_agent.runtime.deadlines import observe_run_deadline
from travel_agent.services.day_planning import default_walking_days


async def candidate_gate_node(
    state: TravelAgentState,
    config: Optional[RunnableConfig] = None,
) -> Dict[str, Any]:
    if state.composition_failure_context and any(
        strip_round_suffix(agent) == "itinerary_planner" and status == "failed"
        for agent, status in state.agent_status.items()
    ):
        _deadline, observation = _observe_deadline(state)
        if observation is not None and observation.composition_closed:
            return {"candidate_gate_status": "passed", "candidate_gate_route": "passed"}
        return _composition_repair_update(
            state,
            {
                "candidate_gate_status": "composition_repair",
                "candidate_gate_route": "composition_repair",
            },
        )
    try:
        catalog, impacts, gaps = build_candidate_catalog(state)
    except CandidateGateIntegrityError as exc:
        return _catalog_contract_update(
            state,
            reason_code=exc.reason_code,
            message=str(exc),
            worker_kind=exc.worker_kind,
        )
    except (KeyError, ValueError) as exc:
        return _catalog_contract_update(
            state,
            reason_code="candidate_catalog_contract_invalid",
            message=str(exc),
        )

    if state.intent_spec is None:
        return _catalog_contract_update(
            state,
            reason_code="missing_intent_spec",
            message="candidate evaluation requires an IntentSpec",
            base_update={"recommendation_catalog": catalog},
        )
    catalog, selection_plan, evaluation_cache = await evaluate_catalog(state, catalog)

    packet_workers = {
        candidate.candidate_id: packet.worker_kind
        for packet in catalog.research_packets
        for candidate in packet.candidates
    }
    candidate_index = catalog.candidate_index()
    try:
        passed_by_worker: dict[str, int] = defaultdict(int)
        passed_kinds_by_worker: dict[str, set[str]] = defaultdict(set)
        for admission in catalog.admission_results:
            if admission.status != "passed":
                continue
            worker = packet_workers[admission.candidate_id]
            passed_by_worker[worker] += 1
            passed_kinds_by_worker[worker].add(
                candidate_index[admission.candidate_id].candidate_kind
            )
    except KeyError as exc:
        return _catalog_contract_update(
            state,
            reason_code="candidate_admission_reference_invalid",
            message=f"candidate admission references an unknown candidate: {exc}",
        )

    base_update: Dict[str, Any] = {
        "recommendation_catalog": catalog,
        "candidate_selection_plan": selection_plan,
        "candidate_intent_evaluation_cache": evaluation_cache,
        "weather_impacts": {impact.weather_impact_id: impact for impact in impacts},
    }
    required_workers = _required_workers(state)
    missing_workers = sorted(
        worker for worker in required_workers if passed_by_worker[worker] == 0
    )
    for worker in missing_workers:
        gaps.append(
            CandidateResearchGap(
                gap_id=_gap_id(worker, "missing_candidate"),
                worker_kind=worker,
                generation_id=state.planning_generation.generation_id,
                reason="missing_candidate",
            )
        )
    required_candidate_kinds = _required_candidate_kinds(state)
    coverage_workers: set[str] = set()
    for worker, required_kinds in required_candidate_kinds.items():
        if worker not in required_workers:
            continue
        for candidate_kind in sorted(
            required_kinds - passed_kinds_by_worker.get(worker, set())
        ):
            coverage_workers.add(worker)
            gaps.append(
                CandidateResearchGap(
                    gap_id=_gap_id(worker, "missing_candidate", candidate_kind),
                    worker_kind=worker,
                    generation_id=state.planning_generation.generation_id,
                    reason="missing_candidate",
                    field_path=f"candidate_kind.{candidate_kind}",
                )
            )
    long_distance_gaps = _long_distance_gaps(state, catalog, required_workers)
    destination_coverage_gaps = _destination_coverage_gaps(
        state,
        catalog,
        required_workers,
    )
    intent_gaps = _intent_research_gaps(
        state,
        catalog,
        selection_plan.uncovered_intent_ids,
    )
    gaps.extend([*long_distance_gaps, *destination_coverage_gaps, *intent_gaps])
    blocked_workers = sorted(
        set(missing_workers)
        | coverage_workers
        | {gap.worker_kind for gap in long_distance_gaps}
        | {gap.worker_kind for gap in destination_coverage_gaps}
        | {gap.worker_kind for gap in intent_gaps}
    )

    try:
        observed_deadline, observation = _observe_deadline(state)
    except ValueError as exc:
        return _catalog_contract_update(
            state,
            reason_code="run_deadline_invalid",
            message=str(exc),
            base_update=base_update,
        )
    if _research_closeout_can_skip_connector_pass(state, observation):
        return _passed_update(
            state,
            base_update=base_update,
            gaps=_classify_candidate_gaps(
                gaps,
                candidate_index,
                prior_gaps=state.candidate_research_gaps,
            ),
            deadline=observed_deadline,
        )

    planned_agents = {
        strip_round_suffix(agent) for group in state.execution_plan for agent in group
    }
    gaps = _classify_candidate_gaps(
        gaps,
        candidate_index,
        prior_gaps=state.candidate_research_gaps,
    )
    packets_by_worker = {
        packet.worker_kind: packet for packet in catalog.research_packets
    }
    attributions = dict(state.gate_failure_attributions or {})
    failure_ledger = {
        key: list(dict.fromkeys(values))
        for key, values in (state.candidate_gate_failure_signatures or {}).items()
    }
    primary_gap, gaps, attributions, failure_ledger, signals = _resolve_research_target(
        state,
        gaps=gaps,
        blocked_workers=blocked_workers,
        packets_by_worker=packets_by_worker,
        attributions=attributions,
        failure_ledger=failure_ledger,
    )
    base_update["candidate_research_gaps"] = gaps
    connector_gaps: list[LocalConnectorGap] = []
    unresolved_connector_gaps: list[LocalConnectorGap] = []
    if (
        primary_gap is None
        and any(passed_by_worker.values())
        and not long_distance_gaps
        and "itinerary_planner" in planned_agents
        and state.trip_workspace_v2 is None
    ):
        if state.placement_skeleton is None:
            if state.agent_status.get("itinerary_planner") == "failed":
                return _composition_repair_update(
                    state,
                    {
                        **base_update,
                        "candidate_gate_status": "composition_repair",
                        "candidate_gate_route": "composition_repair",
                        "candidate_gate_failure_signatures": failure_ledger,
                        "gate_failure_attributions": _record_attribution(
                            state.model_copy(
                                update={"gate_failure_attributions": attributions}
                            ),
                            gate_class=GateClass.COMPOSITION,
                            disposition=GateDisposition.COMPOSITION_REPAIR,
                            reason_code="placement_skeleton_unavailable",
                        ),
                        "last_error": str(
                            state.last_error or "placement skeleton unavailable"
                        ),
                    },
                )
            assignments = dict(state.agent_assignments)
            assignments["itinerary_planner"] = {
                **dict(assignments.get("itinerary_planner") or {}),
                "required_candidate_kinds": sorted(
                    required_candidate_kinds.get("destination_researcher", set())
                ),
                "objective": (
                    "只选择已准入 Visit/Dining/Lodging 与日期匹配的 long-distance 主方案，"
                    "生成不含任何市内 Transport placement 的排期骨架；不得猜路线或端点。"
                ),
            }
            return {
                **base_update,
                "candidate_gate_status": "needs_research",
                "candidate_gate_route": "itinerary_planner",
                "candidate_gate_failure_signatures": failure_ledger,
                "gate_failure_attributions": attributions,
                "local_connector_gaps": [],
                "agent_assignments": assignments,
            }
        try:
            flexible_requests, required_flexible_pairs = (
                connector_mode_requests_from_constraint_pack(
                    state.placement_skeleton,
                    state.constraint_pack,
                    catalog,
                )
            )
            connector_gaps = extract_local_connector_gaps(
                state.placement_skeleton,
                catalog,
                default_walk_day_ids=default_walking_days(
                    state, state.placement_skeleton
                ),
                weather_data_revision=catalog.weather_data_revision,
                flexible_mode_requests=flexible_requests,
                required_flexible_mode_pairs=required_flexible_pairs,
                required_candidate_kinds=required_candidate_kinds.get(
                    "destination_researcher", set()
                ),
            )
        except ItineraryCompositionError as exc:
            return _composition_repair_update(
                state,
                {
                    **base_update,
                    "candidate_gate_failure_signatures": failure_ledger,
                    "local_connector_gaps": [],
                    "placement_skeleton_failure_context": (
                        _placement_skeleton_verdict(exc)
                    ),
                    "candidate_gate_status": "composition_repair",
                    "candidate_gate_route": "composition_repair",
                    "gate_failure_attributions": _record_attribution(
                        state.model_copy(
                            update={"gate_failure_attributions": attributions}
                        ),
                        gate_class=GateClass.COMPOSITION,
                        disposition=GateDisposition.COMPOSITION_REPAIR,
                        reason_code="placement_skeleton_invalid",
                    ),
                    "last_error": str(exc),
                },
            )
        base_update["placement_skeleton_failure_context"] = None
        passed_ids = {
            admission.candidate_id
            for admission in catalog.admission_results
            if admission.status == "passed" and admission.selection_slot_id is None
        }
        passed_transport = [
            candidate
            for candidate_id, candidate in candidate_index.items()
            if candidate_id in passed_ids and isinstance(candidate, TransportCandidate)
        ]
        unresolved_connector_gaps = [
            gap
            for gap in connector_gaps
            if not any(
                connector_candidate_quality_error(candidate, gap) is None
                for candidate in passed_transport
            )
        ]
        base_update["local_connector_gaps"] = connector_gaps
        if unresolved_connector_gaps:
            # Reclassifying existing gaps would undo this pass's failure decisions.
            gaps = [
                *gaps,
                *_classify_candidate_gaps(
                    [
                        CandidateResearchGap(
                            gap_id=pending.gap_id,
                            worker_kind="transport_researcher",
                            generation_id=state.planning_generation.generation_id,
                            reason="missing_candidate",
                            field_path=f"itinerary.connector.{pending.gap_id}",
                            destination_id=pending.destination_id,
                        )
                        for pending in unresolved_connector_gaps
                    ],
                    candidate_index,
                    prior_gaps=state.candidate_research_gaps,
                ),
            ]
            blocked_workers = ["transport_researcher"]
            (
                primary_gap,
                gaps,
                attributions,
                failure_ledger,
                signals,
            ) = _resolve_research_target(
                state,
                gaps=gaps,
                blocked_workers=blocked_workers,
                packets_by_worker=packets_by_worker,
                attributions=attributions,
                failure_ledger=failure_ledger,
            )

    base_update["candidate_research_gaps"] = gaps
    if attributions != (state.gate_failure_attributions or {}):
        base_update["gate_failure_attributions"] = attributions
    if failure_ledger != (state.candidate_gate_failure_signatures or {}):
        base_update["candidate_gate_failure_signatures"] = failure_ledger
    if primary_gap is None:
        if state.placement_skeleton is not None:
            final_assignments = dict(state.agent_assignments)
            final_assignments["itinerary_planner"] = {
                **dict(final_assignments.get("itinerary_planner") or {}),
                "required_candidate_kinds": sorted(
                    required_candidate_kinds.get("destination_researcher", set())
                ),
                "objective": "只用 placement skeleton 与通过质量门的 exact Provider routes 物化正式行程。",
            }
            base_update["agent_assignments"] = final_assignments
        if not blocked_workers:
            return {
                **base_update,
                "candidate_gate_status": "passed",
                "candidate_gate_route": "passed",
            }
        return _passed_update(state, base_update=base_update, gaps=gaps)

    return schedule_targeted_research(
        state,
        catalog=catalog,
        primary_gap=primary_gap,
        gaps=gaps,
        unresolved_connector_gaps=unresolved_connector_gaps,
        signals=signals,
        failure_ledger=failure_ledger,
        attributions=attributions,
        base_update=base_update,
        packet_workers=packet_workers,
        required_candidate_kinds=required_candidate_kinds,
        passed_kinds_by_worker=passed_kinds_by_worker,
        coverage_workers=coverage_workers,
    )


def route_after_candidate_gate(state: TravelAgentState) -> str:
    """Recheck the deadline before routing into another research round."""
    route = state.candidate_gate_route or "passed"
    deadline = state.run_deadline
    if deadline is None:
        return route
    try:
        _observed, observation = observe_run_deadline(deadline)
    except ValueError:
        return "passed"
    if observation.research_closed:
        if not observation.composition_closed and (
            route == "composition_repair"
            or (
                route == "transport_researcher"
                and is_structural_connector_round(state, route)
            )
        ):
            return route
        return route if route == "passed" else "passed"
    return route
