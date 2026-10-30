"""Compile the exact Provider operations of an approved research plan.

Every operation is built from server-owned state: the approved research query
plan, the capability assignments, the controlled trip identity and the semantic
receipt. Model tool arguments are never an input. Calls whose exact parameters
cannot be derived up front are intentionally left out and recorded as
limitations; execution fails closed instead of widening the check.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from travel_agent.planning.assignments import resolve_agent_assignment
from travel_agent.planning.research.accommodation.binding import (
    build_amap_lodging_search_arguments,
    build_nominatim_lodging_search_arguments,
)
from travel_agent.planning.research.authorization_context import (
    RESEARCH_WORKER_KINDS,
    research_authorization_scope,
)
from travel_agent.planning.research.destination.dining_binding import (
    amap_dining_keywords,
    build_amap_dining_search_arguments,
    select_amap_dining_query,
)
from travel_agent.planning.research.destination.discovery import (
    build_global_place_search_arguments,
    build_semantic_amap_arguments,
    build_semantic_discovery_arguments,
)
from travel_agent.planning.research.destination.scope import (
    _SCOPED_DISCOVERY_TOOLS,
    build_destination_boundaries,
)
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.operation_authority import (
    ApprovedOperationManifest,
    AuthorizedToolOperation,
    OperationApproval,
    build_authorized_operation,
    build_operation_approval,
)
from travel_agent.planning.research.provider_assignments import (
    parse_provider_evidence_assignments,
)
from travel_agent.planning.research.query_contracts import (
    ResearchQuery,
    ResearchQueryPlan,
)
from travel_agent.planning.research.transport.rail.binding import (
    build_rail_station_code_arguments,
    build_rail_ticket_arguments,
    rail_ticket_station_pairs,
)
from travel_agent.planning.research.transport.rail.parsing import (
    _builtin_station_telecode,
)
from travel_agent.tools.fallback import build_fallback_args, get_fallback_tool

logger = logging.getLogger(__name__)


_MAX_OPERATIONS = 256


_WORKER_DOMAINS: Dict[str, frozenset[ResearchDomain]] = {
    "destination_researcher": frozenset(
        {ResearchDomain.VISIT, ResearchDomain.DINING}
    ),
    "accommodation_researcher": frozenset({ResearchDomain.LODGING}),
    "transport_researcher": frozenset(
        {ResearchDomain.LOCAL_TRANSPORT, ResearchDomain.LONG_DISTANCE_TRANSPORT}
    ),
}


# 参数来自 Provider 返回值而非批准计划，无法在批准时精确预编译。
_UNCOMPILED_LIMITATIONS = {
    "destination_researcher": (
        "maps_search_detail:provider_place_id_is_dynamic",
        "place_operating_information:provider_place_name_is_dynamic",
        "knowledge_search:not_precompiled",
    ),
    "accommodation_researcher": (
        "maps_search_detail:provider_place_id_is_dynamic",
        "knowledge_search:not_precompiled",
    ),
    "transport_researcher": (
        "rail_station_point:provider_station_name_is_dynamic",
        "rail_mcp_station_codes:provider_station_codes_are_dynamic",
        "rail_temporal_preflight:date_capability_is_dynamic",
        "rail_reference_date:date_capability_is_dynamic",
        "local_route_search:itinerary_endpoints_are_dynamic",
        "knowledge_search:not_precompiled",
    ),
}


@dataclass(frozen=True)
class CompiledResearchOperations:
    """Compiled manifest plus the calls that could not be covered."""

    manifest: Optional[ApprovedOperationManifest]
    limitations: Tuple[str, ...]

    def approval(self) -> Optional[OperationApproval]:
        if self.manifest is None:
            return None
        return build_operation_approval(manifest=self.manifest)


def _limitation(limitations: List[str], code: str) -> None:
    if code not in limitations:
        limitations.append(code)


def _assigned_queries(
    state: Any,
    *,
    worker_kind: str,
    plan: ResearchQueryPlan,
    limitations: List[str],
) -> Optional[tuple[Dict[str, Any], List[ResearchQuery]]]:
    try:
        _key, assignment = resolve_agent_assignment(
            getattr(state, "agent_assignments", None) or {}, worker_kind
        )
    except (TypeError, ValueError):
        _limitation(limitations, f"{worker_kind}:assignment_missing")
        return None
    query_ids = assignment.get("research_query_ids")
    if not isinstance(query_ids, list) or not query_ids:
        _limitation(limitations, f"{worker_kind}:assignment_query_ids_missing")
        return None
    index = plan.query_index()
    if not set(query_ids) <= set(index):
        _limitation(limitations, f"{worker_kind}:assignment_query_ids_unknown")
        return None
    domains = _WORKER_DOMAINS[worker_kind]
    queries = [
        index[query_id]
        for query_id in query_ids
        if index[query_id].domain in domains
    ]
    if not queries:
        _limitation(limitations, f"{worker_kind}:assignment_has_no_domain_queries")
        return None
    return assignment, queries


def _validated_assignment(
    state: Any,
    *,
    worker_kind: str,
    assignment: Mapping[str, Any],
    limitations: List[str],
) -> bool:
    try:
        parse_provider_evidence_assignments(
            assignment,
            expected_worker=worker_kind,
            expected_run_id=str(getattr(state, "run_id", "") or ""),
            expected_constraint_pack_revision=int(
                getattr(state, "constraint_pack_revision", 0) or 0
            ),
        )
        return True
    except (TypeError, ValueError):
        _limitation(limitations, f"{worker_kind}:provider_evidence_assignment_invalid")
        return False


def _dependencies(query: ResearchQuery) -> Tuple[str, ...]:
    return tuple(query.fallback_after_query_ids)


def _add_operation(
    operations: Dict[str, AuthorizedToolOperation],
    limitations: List[str],
    *,
    tool_name: str,
    query_id: str,
    arguments: Dict[str, Any],
    fallback_after_query_ids: Tuple[str, ...] = (),
) -> None:
    try:
        operation = build_authorized_operation(
            tool_name=tool_name,
            query_id=query_id,
            arguments=arguments,
            fallback_after_query_ids=fallback_after_query_ids,
        )
    except ValueError:
        _limitation(limitations, f"operation_arguments_invalid:{tool_name}")
        return
    operations[operation.operation_id] = operation


def _compile_destination_operations(
    *,
    state: Any,
    assignment: Mapping[str, Any],
    queries: Sequence[ResearchQuery],
    operations: Dict[str, AuthorizedToolOperation],
    limitations: List[str],
) -> None:
    identity = getattr(state, "controlled_trip_identity", None) or {}
    boundaries = [
        boundary
        for boundary in build_destination_boundaries(identity)
        if boundary.get("destination_id") and boundary.get("country_code")
    ]
    if not boundaries:
        _limitation(limitations, "destination_researcher:no_destination_boundary")
        return
    assigned = _validated_assignment(
        state,
        worker_kind="destination_researcher",
        assignment=assignment,
        limitations=limitations,
    )
    if not assigned:
        return

    cn_only = all(
        str(boundary.get("country_code") or "").casefold() == "cn"
        for boundary in boundaries
    )
    boundary_by_id = {
        str(boundary.get("destination_id") or ""): boundary
        for boundary in boundaries
    }

    for query in queries:
        boundary = boundary_by_id.get(query.destination_id)
        if boundary is None:
            _limitation(limitations, "destination_researcher:query_destination_unknown")
            continue
        if query.provider_route == "global_place_search":
            kind = "visit" if query.domain is ResearchDomain.VISIT else "dining"
            _add_operation(
                operations,
                limitations,
                tool_name="global_place_search",
                query_id=query.query_id,
                arguments=build_global_place_search_arguments(
                    query, boundary, kind
                ),
                fallback_after_query_ids=_dependencies(query),
            )
            continue
        if cn_only:
            _add_operation(
                operations,
                limitations,
                tool_name="maps_text_search",
                query_id=query.query_id,
                arguments=build_semantic_amap_arguments(query, boundary),
                fallback_after_query_ids=_dependencies(query),
            )
        discovery_arguments = build_semantic_discovery_arguments(query)
        for tool_name in _SCOPED_DISCOVERY_TOOLS:
            _add_operation(
                operations,
                limitations,
                tool_name=tool_name,
                query_id=query.query_id,
                arguments=discovery_arguments,
                fallback_after_query_ids=_dependencies(query),
            )
            fallback = get_fallback_tool(tool_name)
            if fallback is None:
                continue
            fallback_name, adapter_key = fallback
            _add_operation(
                operations,
                limitations,
                tool_name=fallback_name,
                query_id=query.query_id,
                arguments=build_fallback_args(
                    tool_name,
                    fallback_name,
                    adapter_key,
                    discovery_arguments,
                ),
                fallback_after_query_ids=(query.query_id,),
            )

    dining_by_destination: Dict[str, List[ResearchQuery]] = {}
    for query in queries:
        if query.domain is ResearchDomain.DINING:
            dining_by_destination.setdefault(query.destination_id, []).append(query)
    for boundary in boundaries:
        if str(boundary.get("country_code") or "").casefold() != "cn":
            continue
        dining_queries = dining_by_destination.get(
            str(boundary.get("destination_id") or ""), []
        )
        if not dining_queries or not str(boundary.get("name") or "").strip():
            continue
        amap_query = select_amap_dining_query(dining_queries)
        _add_operation(
            operations,
            limitations,
            tool_name="maps_text_search",
            query_id=amap_query.query_id,
            arguments=build_amap_dining_search_arguments(
                keywords=amap_dining_keywords(amap_query),
                city=str(boundary.get("name") or ""),
            ),
            fallback_after_query_ids=_dependencies(amap_query),
        )


def _compile_accommodation_operations(
    *,
    state: Any,
    assignment: Mapping[str, Any],
    queries: Sequence[ResearchQuery],
    operations: Dict[str, AuthorizedToolOperation],
    limitations: List[str],
) -> None:
    identity = getattr(state, "controlled_trip_identity", None) or {}
    destinations = [
        item
        for item in identity.get("destinations") or []
        if isinstance(item, Mapping) and str(item.get("name") or "").strip()
    ]
    if not destinations:
        _limitation(limitations, "accommodation_researcher:no_destination")
        return
    if not _validated_assignment(
        state,
        worker_kind="accommodation_researcher",
        assignment=assignment,
        limitations=limitations,
    ):
        return

    destination_by_place_id = {
        str(destination.get("place_id") or ""): destination
        for destination in destinations
    }

    for query in queries:
        destination = destination_by_place_id.get(query.destination_id)
        if destination is None:
            _limitation(
                limitations, "accommodation_researcher:query_destination_unknown"
            )
            continue
        raw_country_code = str(destination.get("country_code") or "").lower()
        country_code = raw_country_code.strip()
        if not country_code or len(country_code) != 2:
            _limitation(
                limitations,
                "accommodation_researcher:destination_country_missing",
            )
            continue
        destination_name = str(destination.get("name") or "").strip()
        if raw_country_code == "cn":
            arguments = build_amap_lodging_search_arguments(
                query_text=query.query_text, dest_name=destination_name
            )
            tool_name = "maps_text_search"
        else:
            arguments = build_nominatim_lodging_search_arguments(
                query_text=query.query_text,
                country_code=country_code,
                destination_latitude=destination.get("latitude"),
                destination_longitude=destination.get("longitude"),
            )
            tool_name = "global_place_search"
        _add_operation(
            operations,
            limitations,
            tool_name=tool_name,
            query_id=query.query_id,
            arguments=arguments,
            fallback_after_query_ids=_dependencies(query),
        )


def _identity_places(state: Any) -> Dict[str, Mapping[str, Any]]:
    identity = getattr(state, "controlled_trip_identity", None) or {}
    origin = identity.get("origin")
    destinations = identity.get("destinations")
    places: List[Mapping[str, Any]] = []
    if isinstance(origin, Mapping):
        places.append(origin)
    if isinstance(destinations, list):
        places.extend(item for item in destinations if isinstance(item, Mapping))
    return {
        str(item.get("place_id") or "").strip(): item
        for item in places
        if str(item.get("place_id") or "").strip()
    }


def _compile_transport_operations(
    *,
    state: Any,
    assignment: Mapping[str, Any],
    queries: Sequence[ResearchQuery],
    operations: Dict[str, AuthorizedToolOperation],
    limitations: List[str],
) -> None:
    try:
        provider_assignments = parse_provider_evidence_assignments(
            assignment,
            expected_worker="transport_researcher",
            expected_run_id=str(getattr(state, "run_id", "") or ""),
            expected_constraint_pack_revision=int(
                getattr(state, "constraint_pack_revision", 0) or 0
            ),
        )
    except (TypeError, ValueError):
        _limitation(limitations, "transport_researcher:provider_evidence_assignment_invalid")
        return
    long_distance_query_ids = [
        query.query_id
        for query in queries
        if query.domain is ResearchDomain.LONG_DISTANCE_TRANSPORT
    ]
    if not long_distance_query_ids:
        _limitation(limitations, "transport_researcher:no_long_distance_query")
    rail_query_id = long_distance_query_ids[0] if long_distance_query_ids else ""
    places = _identity_places(state)
    route_legs = [
        item.scope.route_leg
        for item in provider_assignments
        if item.scope.transport_class == "long_distance"
        and item.scope.route_leg is not None
    ]
    if not route_legs:
        _limitation(limitations, "transport_researcher:no_exact_route_leg")
    for route_leg in route_legs:
        if not rail_query_id:
            break
        origin = places.get(str(route_leg.from_place_id or ""))
        destination = places.get(str(route_leg.to_place_id or ""))
        if origin is None or destination is None:
            _limitation(limitations, "transport_researcher:route_endpoint_not_controlled")
            continue
        if (
            str(origin.get("country_code") or "").lower() != "cn"
            or str(destination.get("country_code") or "").lower() != "cn"
        ):
            _limitation(limitations, "transport_researcher:route_not_cn_pair")
            continue
        origin_name = str(origin.get("name") or "").strip()
        destination_name = str(destination.get("name") or "").strip()
        if (
            not origin_name
            or not destination_name
            or origin_name == destination_name
        ):
            _limitation(limitations, "transport_researcher:route_endpoint_name_missing")
            continue
        service_date = route_leg.service_date.isoformat()
        _add_operation(
            operations,
            limitations,
            tool_name="get-station-code-of-citys",
            query_id=rail_query_id,
            arguments=build_rail_station_code_arguments(
                origin_name=origin_name, dest_name=destination_name
            ),
        )
        from_code = _builtin_station_telecode(origin_name)
        to_code = _builtin_station_telecode(destination_name)
        if not from_code or not to_code:
            _limitation(
                limitations,
                "transport_researcher:rail_builtin_telecode_missing",
            )
            continue
        for pair in rail_ticket_station_pairs(
            origin_name=origin_name,
            dest_name=destination_name,
            from_code=from_code,
            to_code=to_code,
        ):
            _add_operation(
                operations,
                limitations,
                tool_name="get-tickets",
                query_id=rail_query_id,
                arguments=build_rail_ticket_arguments(
                    service_date=service_date,
                    from_code=pair[0],
                    to_code=pair[1],
                ),
            )


def compile_research_operation_manifest(
    state: Any, *, approval_token: Optional[str] = None
) -> CompiledResearchOperations:
    """Compile every operation that can be proven from the approved plan."""

    limitations: List[str] = []
    token = str(
        approval_token
        or getattr(state, "plan_gate_approval_token", "")
        or ""
    ).strip()
    if not token:
        return CompiledResearchOperations(None, ("approval_token_missing",))
    scope = research_authorization_scope(state, approval_token=token)
    if scope is None:
        return CompiledResearchOperations(
            None, ("authorization_scope_missing:request_contract_or_query_plan",)
        )

    plan = getattr(state, "research_query_plan", None)
    if not isinstance(plan, ResearchQueryPlan):
        try:
            plan = ResearchQueryPlan.model_validate(plan)
        except (TypeError, ValueError):
            return CompiledResearchOperations(None, ("research_query_plan_invalid",))
    if plan.generation_id != scope["generation_id"]:
        return CompiledResearchOperations(
            None, ("research_query_plan_generation_mismatch",)
        )

    operations: Dict[str, AuthorizedToolOperation] = {}
    planned_workers = {
        str(worker)
        for group in getattr(state, "execution_plan", []) or []
        for worker in (group if isinstance(group, list) else [group])
        if str(worker) in RESEARCH_WORKER_KINDS
    }
    for worker_kind in sorted(planned_workers or set(RESEARCH_WORKER_KINDS)):
        assigned = _assigned_queries(
            state, worker_kind=worker_kind, plan=plan, limitations=limitations
        )
        if assigned is None:
            _limitation(limitations, f"{worker_kind}:no_compiled_operation")
            return CompiledResearchOperations(None, tuple(limitations))
        assignment, queries = assigned
        if str(assignment.get("generation_id") or "") != plan.generation_id:
            _limitation(limitations, f"{worker_kind}:assignment_generation_mismatch")
            return CompiledResearchOperations(None, tuple(limitations))
        operation_count = len(operations)
        if worker_kind == "destination_researcher":
            _compile_destination_operations(
                state=state,
                assignment=assignment,
                queries=queries,
                operations=operations,
                limitations=limitations,
            )
        elif worker_kind == "accommodation_researcher":
            _compile_accommodation_operations(
                state=state,
                assignment=assignment,
                queries=queries,
                operations=operations,
                limitations=limitations,
            )
        else:
            _compile_transport_operations(
                state=state,
                assignment=assignment,
                queries=queries,
                operations=operations,
                limitations=limitations,
            )
        if len(operations) == operation_count:
            _limitation(limitations, f"{worker_kind}:no_compiled_operation")
            return CompiledResearchOperations(None, tuple(limitations))
        query_index = plan.query_index()
        required_domains = {query.domain for query in queries}
        covered_domains = {
            query_index[operation.query_id].domain
            for operation in operations.values()
            if operation.query_id in query_index
        }
        missing_domains = sorted(required_domains - covered_domains, key=lambda item: item.value)
        if missing_domains:
            for domain in missing_domains:
                _limitation(limitations, f"{worker_kind}:{domain.value}:no_compiled_operation")
            return CompiledResearchOperations(None, tuple(limitations))
        for code in _UNCOMPILED_LIMITATIONS[worker_kind]:
            _limitation(limitations, f"{worker_kind}:{code}")

    if not operations:
        _limitation(limitations, "no_operation_could_be_compiled")
        logger.warning(
            "research operation manifest not compiled run_id=%s limitations=%s",
            scope["run_id"],
            limitations,
        )
        return CompiledResearchOperations(None, tuple(limitations))
    if len(operations) > _MAX_OPERATIONS:
        _limitation(limitations, "operation_count_exceeds_limit")
        logger.warning(
            "research operation manifest rejected run_id=%s operations=%d",
            scope["run_id"],
            len(operations),
        )
        return CompiledResearchOperations(None, tuple(limitations))
    try:
        manifest = ApprovedOperationManifest(
            run_id=scope["run_id"],
            generation_id=scope["generation_id"],
            identity_hash=scope["identity_hash"],
            confirmation_hash=scope["confirmation_hash"],
            query_plan_hash=scope["query_plan_hash"],
            approval_token=token,
            operations=tuple(
                operations[operation_id] for operation_id in sorted(operations)
            ),
        )
    except (TypeError, ValueError):
        _limitation(limitations, "operation_manifest_invalid")
        return CompiledResearchOperations(None, tuple(limitations))
    if limitations:
        logger.warning(
            "research operations compiled with limitations run_id=%s operations=%d limitations=%s",
            scope["run_id"],
            len(operations),
            limitations,
        )
    return CompiledResearchOperations(manifest, tuple(limitations))


def compile_and_approve_research_operations(
    state: Any, *, approval_token: Optional[str] = None
) -> tuple[
    Optional[ApprovedOperationManifest],
    Optional[OperationApproval],
    Tuple[str, ...],
]:
    """Approval-time helper for the plan gate and its tests."""

    compiled = compile_research_operation_manifest(
        state, approval_token=approval_token
    )
    approval = compiled.approval()
    return compiled.manifest, approval, compiled.limitations
