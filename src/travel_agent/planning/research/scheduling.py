from __future__ import annotations

from typing import Any, Dict, Mapping

from travel_agent.entities.provider_evidence import (
    ProviderRouteLegScope,
    build_provider_evidence_assignments,
    build_required_long_distance_legs,
    dump_provider_evidence_assignments,
    explicit_cross_day_return_required,
    scope_attempt_numbers,
)
from travel_agent.entities.research_query_plan import ResearchQueryKind
from travel_agent.entities.state import TravelAgentState
from travel_agent.planning.itinerary.connectors import LocalConnectorGap
from travel_agent.planning.outcomes import (
    CandidateResearchGap,
    GateDisposition,
    GateFailureAttribution,
)
from travel_agent.planning.research.assignment_policy import (
    _deterministically_rejected_candidate_ids,
    _long_distance_instruction,
    _recommended_tools,
)
from travel_agent.planning.research.attribution import _record_attribution
from travel_agent.planning.research.candidates import TransportCandidate
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.planning.research.deadlines import (
    _closeout_blocks_targeted_round,
    _observe_deadline,
)
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.failure_signals import ProviderFailureSignal
from travel_agent.planning.research.retry import _retry_scope_for_gap
from travel_agent.planning.research.transitions import (
    _catalog_contract_update,
    _passed_update,
)
from travel_agent.services.research_query_planner import (
    append_structural_connector_query,
    append_targeted_repair_query,
)


def schedule_targeted_research(
    state: TravelAgentState,
    *,
    catalog: RecommendationCatalog,
    primary_gap: CandidateResearchGap,
    gaps: list[CandidateResearchGap],
    unresolved_connector_gaps: list[LocalConnectorGap],
    signals: list[ProviderFailureSignal],
    failure_ledger: Dict[str, list[str]],
    attributions: Dict[str, GateFailureAttribution],
    base_update: Dict[str, Any],
    packet_workers: Mapping[str, str],
    required_candidate_kinds: Mapping[str, set[str]],
    passed_kinds_by_worker: Mapping[str, set[str]],
    coverage_workers: set[str],
) -> Dict[str, Any]:
    worker = primary_gap.worker_kind
    domain = primary_gap.research_domain or ResearchDomain.VISIT
    scoped_gaps = [primary_gap]
    connector_gap = next(
        (gap for gap in unresolved_connector_gaps if gap.gap_id == primary_gap.gap_id),
        None,
    )
    connector_round_gaps = (
        list(unresolved_connector_gaps) if connector_gap is not None else []
    )
    required_long_distance_legs = build_required_long_distance_legs(
        state.controlled_trip_identity or {},
        cross_day_return_required=explicit_cross_day_return_required(
            state.user_query or ""
        ),
    )
    long_distance_legs: list[ProviderRouteLegScope] = []
    if domain == ResearchDomain.LONG_DISTANCE_TRANSPORT:
        long_distance_scope_id = primary_gap.provider_evidence_scope_id
        if long_distance_scope_id is None and primary_gap.candidate_id is not None:
            scoped_candidate = catalog.candidate_index().get(primary_gap.candidate_id)
            if (
                isinstance(scoped_candidate, TransportCandidate)
                and scoped_candidate.transport_class == "long_distance"
            ):
                long_distance_scope_id = scoped_candidate.provider_evidence_scope_id
        scoped_assignments = build_provider_evidence_assignments(
            run_id=state.run_id,
            constraint_pack_revision=state.constraint_pack_revision,
            worker_kind="transport_researcher",
            controlled_trip_identity=state.controlled_trip_identity or {},
            prior_scope_attempts=scope_attempt_numbers(
                state.provider_evidence_outcomes
            ),
            transport_classes=["long_distance"],
            long_distance_legs=required_long_distance_legs,
        )
        legs_by_scope_id = {
            assignment.scope.scope_id: assignment.scope.route_leg
            for assignment in scoped_assignments
            if assignment.scope.route_leg is not None
        }
        primary_long_distance_leg = legs_by_scope_id.get(long_distance_scope_id or "")
        if primary_long_distance_leg is None:
            return _catalog_contract_update(
                state,
                reason_code="candidate_gate_long_distance_scope_invalid",
                message="long-distance gap does not match a current exact route leg",
                base_update=base_update,
            )
        companion_legs: Dict[str, ProviderRouteLegScope] = {}
        for gap in gaps:
            if gap.gap_id == primary_gap.gap_id:
                continue
            if gap.worker_kind != worker:
                continue
            if gap.field_path != "transport_class.long_distance":
                continue
            if gap.status not in {"open", "researching"}:
                continue
            companion_scope_id = gap.provider_evidence_scope_id
            if (
                companion_scope_id is None
                or companion_scope_id == long_distance_scope_id
                or companion_scope_id in companion_legs
            ):
                continue
            companion_leg = legs_by_scope_id.get(companion_scope_id)
            if companion_leg is None:
                continue
            scoped_gaps.append(gap)
            companion_legs[companion_scope_id] = companion_leg
        long_distance_legs = [
            primary_long_distance_leg,
            *(
                leg
                for _key, leg in sorted(
                    companion_legs.items(),
                    key=lambda item: (item[1].leg_role, item[0]),
                )
            ),
        ]
    attempt_scope = _retry_scope_for_gap(primary_gap)
    accumulated_signatures = list(
        dict.fromkeys(
            [
                *failure_ledger.get(attempt_scope, []),
                *(signal.signature for signal in signals),
            ]
        )
    )
    failure_ledger[attempt_scope] = accumulated_signatures
    # The research window may have closed while the assignment was being prepared.
    try:
        observed_deadline, observation = _observe_deadline(state)
    except ValueError as exc:
        return _catalog_contract_update(
            state,
            reason_code="run_deadline_invalid",
            message=str(exc),
            base_update=base_update,
        )
    if _closeout_blocks_targeted_round(observation, connector_round_gaps):
        return _passed_update(
            state,
            base_update={
                **base_update,
                "candidate_gate_failure_signatures": failure_ledger,
            },
            gaps=gaps,
            deadline=observed_deadline,
        )

    attempts = dict(state.candidate_gate_attempts or {})
    attempts[attempt_scope] = attempts.get(attempt_scope, 0) + 1
    researched_gap_ids = {gap.gap_id for gap in scoped_gaps}
    researching_gaps = [
        gap.model_copy(
            update={
                "status": "researching",
                "attempted_signatures": list(
                    dict.fromkeys([*gap.attempted_signatures, *accumulated_signatures])
                ),
            }
        )
        if gap.gap_id in researched_gap_ids and gap.status == "open"
        else gap
        for gap in gaps
    ]
    excluded_tools = sorted({signal.tool_name for signal in signals})
    recommended_tools = _recommended_tools(state, worker, set(excluded_tools), domain)
    deterministically_rejected_ids = _deterministically_rejected_candidate_ids(
        catalog, packet_workers, worker
    )
    repair_query_ids: list[str] = []
    updated_query_plan = state.research_query_plan
    if connector_round_gaps and updated_query_plan is not None:
        destination_names = {
            str(destination.get("place_id") or ""): str(
                destination.get("name") or destination.get("display_name") or ""
            )
            for destination in (state.controlled_trip_identity or {}).get(
                "destinations", []
            )
            if isinstance(destination, Mapping)
        }
        gaps_by_destination: dict[str, list[LocalConnectorGap]] = {}
        for gap in connector_round_gaps:
            gaps_by_destination.setdefault(gap.destination_id, []).append(gap)
        for destination_id, destination_gaps in sorted(gaps_by_destination.items()):
            updated_query_plan, connector_query = append_structural_connector_query(
                updated_query_plan,
                destination_id=destination_id,
                destination_name=destination_names.get(destination_id)
                or destination_id,
                route_pairs=[
                    (gap.from_place_id, gap.to_place_id) for gap in destination_gaps
                ],
            )
            repair_query_ids.append(connector_query.query_id)
        base_update["research_query_plan"] = updated_query_plan
    elif (
        primary_gap.intent_id is not None
        and primary_gap.destination_id is not None
        and state.intent_spec is not None
        and updated_query_plan is not None
    ):
        intent = next(
            (
                item
                for item in state.intent_spec.active_items
                if item.intent_id == primary_gap.intent_id
            ),
            None,
        )
        if intent is not None:
            destination_name = next(
                (
                    str(destination.get("name") or "")
                    for destination in (state.controlled_trip_identity or {}).get(
                        "destinations", []
                    )
                    if isinstance(destination, Mapping)
                    and destination.get("place_id") == primary_gap.destination_id
                ),
                primary_gap.destination_id,
            )
            updated_query_plan, targeted_query = append_targeted_repair_query(
                updated_query_plan,
                intent=intent,
                destination_id=primary_gap.destination_id,
                destination_name=destination_name,
                domain=domain,
                desired_candidate_count=primary_gap.desired_candidate_count or 2,
            )
            primary_gap = primary_gap.model_copy(
                update={"query_id": targeted_query.query_id}
            )
            gaps = [
                primary_gap if gap.gap_id == primary_gap.gap_id else gap for gap in gaps
            ]
            researching_gaps = [
                primary_gap.model_copy(update={"status": "researching"})
                if gap.gap_id == primary_gap.gap_id
                else gap
                for gap in researching_gaps
            ]
            scoped_gaps = [
                primary_gap if gap.gap_id == primary_gap.gap_id else gap
                for gap in scoped_gaps
            ]
            repair_query_ids = [targeted_query.query_id]
            if (
                domain in {ResearchDomain.VISIT, ResearchDomain.DINING}
                and targeted_query.provider_route == "web_discovery"
            ):
                repair_query_ids.extend(
                    query.query_id
                    for query in updated_query_plan.queries
                    if query.query_kind == ResearchQueryKind.STRUCTURAL
                    and query.domain == domain
                    and query.destination_id == primary_gap.destination_id
                )
            base_update["research_query_plan"] = updated_query_plan
    gap_summary = [gap.model_dump(mode="json") for gap in scoped_gaps]
    long_distance_instruction = _long_distance_instruction(long_distance_legs)
    connector_instruction = (
        f" 本轮研究 placement skeleton 产生的 {len(connector_round_gaps)} 个精确相邻 connector gap，"
        "每一段都要有 Provider 实测路线；不得更换端点或虚构路线。"
        if connector_round_gaps
        else ""
    )
    connector_payloads: list[dict[str, Any]] = []
    for gap in connector_round_gaps:
        payload = gap.model_dump(mode="json")
        payload["requested_mode"] = (
            gap.requested_flexible_modes[0]
            if gap.preferred_transport_class == "flexible"
            else "public_transit"
        )
        payload["comparison_modes"] = ["walk"] if gap.compare_default_walk else []
        connector_payloads.append(payload)
    assignments = dict(state.agent_assignments)
    assignments[worker] = {
        **dict(assignments.get(worker) or {}),
        "objective": (
            "仅补查以下候选准入缺口；必须保留硬约束、避开已失败 Provider，"
            "并使用独立真实来源。缺少可验证事实时明确返回缺口，不得自产 evidence。"
            f"{connector_instruction}{long_distance_instruction}"
            f" gaps={gap_summary}; "
            f"failure_signatures={accumulated_signatures}"
        ),
        "recommended_tools": recommended_tools,
        "excluded_tools": excluded_tools,
        "failure_signatures": accumulated_signatures,
        "require_current_candidate": True,
        **({"research_query_ids": repair_query_ids} if repair_query_ids else {}),
        **(
            {"excluded_candidate_ids": deterministically_rejected_ids}
            if deterministically_rejected_ids
            else {}
        ),
        **(
            {
                "required_candidate_kinds": sorted(
                    (
                        {"visit"}
                        if domain == ResearchDomain.VISIT
                        else {"dining"}
                        if domain == ResearchDomain.DINING
                        else set()
                    )
                    & (
                        required_candidate_kinds.get(worker, set())
                        - passed_kinds_by_worker.get(worker, set())
                    )
                )
            }
            if worker in coverage_workers
            and domain in {ResearchDomain.VISIT, ResearchDomain.DINING}
            else {}
        ),
        **(
            {
                "required_transport_classes": (
                    sorted(
                        {
                            transport_class
                            for gap in connector_round_gaps
                            for transport_class in gap.allowed_transport_classes
                        }
                    )
                    if connector_round_gaps
                    else ["long_distance"]
                ),
            }
            if connector_round_gaps or domain == ResearchDomain.LONG_DISTANCE_TRANSPORT
            else {}
        ),
        **({"connector_gaps": connector_payloads} if connector_payloads else {}),
    }
    scoped_candidate_kinds = (
        ["visit"]
        if domain == ResearchDomain.VISIT
        else ["dining"]
        if domain == ResearchDomain.DINING
        else None
    )
    scoped_transport_classes = (
        connector_gap.allowed_transport_classes
        if connector_gap is not None
        else ["long_distance"]
        if domain == ResearchDomain.LONG_DISTANCE_TRANSPORT
        else ["public_transit", "flexible"]
        if domain == ResearchDomain.LOCAL_TRANSPORT
        else None
    )
    assignments[worker]["provider_evidence_assignments"] = (
        dump_provider_evidence_assignments(
            build_provider_evidence_assignments(
                run_id=state.run_id,
                constraint_pack_revision=state.constraint_pack_revision,
                worker_kind=worker,
                controlled_trip_identity=state.controlled_trip_identity or {},
                prior_scope_attempts=scope_attempt_numbers(
                    state.provider_evidence_outcomes
                ),
                candidate_kinds=scoped_candidate_kinds,
                transport_classes=scoped_transport_classes,
                long_distance_legs=long_distance_legs or None,
            )
        )
    )
    update = {
        **base_update,
        "candidate_research_gaps": researching_gaps,
        "candidate_gate_status": "needs_research",
        "candidate_gate_route": worker,
        "candidate_gate_attempts": attempts,
        "candidate_gate_failure_signatures": failure_ledger,
        "agent_assignments": assignments,
        "gate_failure_attributions": _record_attribution(
            state.model_copy(update={"gate_failure_attributions": attributions}),
            gate_class=primary_gap.gate_class,
            disposition=GateDisposition.TARGETED_RESEARCH,
            reason_code=primary_gap.reason,
            domain=domain,
            gap_ids=[primary_gap.gap_id],
            failure_signature=accumulated_signatures[-1]
            if accumulated_signatures
            else None,
            retry_attempt=attempts[attempt_scope],
        ),
    }
    if observed_deadline is not None:
        update["run_deadline"] = observed_deadline
    return update
