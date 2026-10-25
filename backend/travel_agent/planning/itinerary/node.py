from __future__ import annotations

import logging
from typing import Any, Dict

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError

from travel_agent.entities.intent_coverage import IntentContractSnapshot
from travel_agent.entities.provider_evidence import (
    build_required_long_distance_legs,
    explicit_cross_day_return_required,
)
from travel_agent.entities.state import TravelAgentState, bounded_repair_context
from travel_agent.llm.router import get_model_router
from travel_agent.llm.task_routing import TaskKind, llm_for_task
from travel_agent.planning.assignments import resolve_agent_assignment
from travel_agent.planning.itinerary.composition import _compose_draft
from travel_agent.planning.itinerary.connector_estimates import _author_connector_routes
from travel_agent.planning.itinerary.connectors import (
    connector_mode_requests_from_constraint_pack,
    extract_local_connector_gaps,
    materialize_skeleton_connectors,
    unfilled_connector_gaps,
)
from travel_agent.planning.itinerary.materialize import (
    _restore_full_catalog,
    materialize_trip_workspace,
)
from travel_agent.planning.itinerary.requirements import (
    _draft_user_input_anchors,
    _required_leg_scope_ids,
)
from travel_agent.planning.nodes import NODE_ITINERARY
from travel_agent.planning.workspace import TripWorkspaceV2
from travel_agent.runtime.deadlines import observe_run_deadline
from travel_agent.services.candidate_selection import (
    catalog_for_candidate_selection,
    catalog_for_workspace_materialization,
)
from travel_agent.services.day_design import apply_day_design
from travel_agent.services.day_planning import (
    default_walking_days,
    disclose_default_walking,
)
from travel_agent.services.geo_dispersion import itinerary_dispersion

logger = logging.getLogger(__name__)


_COMPOSITION_FAILURE_VALIDATION_ERRORS = 3


_OUTPUT_TRUNCATION_MARKERS = ("length limit was reached", "finish_reason=length")


def _is_output_truncation(exc: BaseException) -> bool:
    """Whether this composition failed because the completion hit its ceiling."""
    text = str(exc)
    return any(marker in text for marker in _OUTPUT_TRUNCATION_MARKERS)


def _composition_failure_detail(exc: BaseException) -> str:
    """The part of a composition failure worth replaying to the model."""
    if _is_output_truncation(exc):
        return (
            "OutputTruncated: 上一轮 composition 输出超出单次补全长度上限被截断，"
            "因此不是一份完整 JSON。请输出更紧凑的同一份行程：压缩 theme、"
            "selection_reason 等自由文本字段的长度，不要重复叙述。"
            "**天数、每天的必需落位与所有 candidate_id 一个都不许减** —— "
            "为了变短而删掉行程内容会产出一份错的行程。"
        )
    if isinstance(exc, ValidationError):
        detail = "；".join(
            "{path}: {message}".format(
                path=".".join(str(part) for part in error.get("loc", ())) or "(root)",
                message=str(error.get("msg", "")),
            )
            for error in exc.errors()[:_COMPOSITION_FAILURE_VALIDATION_ERRORS]
        )
    else:
        detail = str(exc)
    return f"{type(exc).__name__}: {detail}"


def _log_composition_dispersion(workspace: TripWorkspaceV2) -> None:
    """Print how spread out each Day is: local connector minutes, and stop span."""
    fact_index = {
        fact.fact_assertion_id: fact
        for packet in workspace.recommendation_catalog.research_packets
        for fact in packet.fact_assertions
    }
    measured = []
    for day_id, dispersion in itinerary_dispersion(workspace.itinerary, fact_index):
        legs = f"{dispersion.local_leg_minutes}min/{dispersion.local_leg_count}legs"
        if dispersion.untimed_local_leg_count:
            legs += f"(+{dispersion.untimed_local_leg_count} untimed)"
        if dispersion.span_km is None:
            span = "span=n/a"
        else:
            pair = dispersion.farthest_pair or ("", "")
            span = f"span={dispersion.span_km:.2f}km[{pair[0]}↔{pair[1]}]"
        measured.append(
            f"{day_id}:local={legs} {span} "
            f"pts={dispersion.located_point_count}/{dispersion.point_count}"
        )
    logger.info("Composition dispersion: %s", " | ".join(measured))


def _composition_phase(state: TravelAgentState) -> str:
    if (
        state.placement_skeleton is None
        or state.trip_workspace_v2 is not None
        or state.composition_failure_context
        or state.placement_skeleton_failure_context
    ):
        return "placement_skeleton"
    return "materialize_connectors"


async def itinerary_planner_node(
    state: TravelAgentState, config: RunnableConfig
) -> Dict[str, Any]:
    full_catalog = state.recommendation_catalog
    if full_catalog is not None:
        if state.candidate_selection_plan is None:
            raise ValueError(
                "itinerary composition requires a Candidate Selection Plan"
            )
        state = state.model_copy(
            update={
                "recommendation_catalog": catalog_for_candidate_selection(
                    full_catalog,
                    state.candidate_selection_plan,
                ),
            }
        )
    output_key, assignment = resolve_agent_assignment(
        state.agent_assignments or {}, NODE_ITINERARY
    )
    phase = _composition_phase(state)
    stage = phase
    unlocatable = set(state.unlocatable_authored_places)
    required_kinds = {
        str(kind)
        for kind in assignment.get("required_candidate_kinds", [])
        if str(kind) in {"visit", "dining"}
    }
    required_legs = build_required_long_distance_legs(
        state.controlled_trip_identity or {},
        cross_day_return_required=explicit_cross_day_return_required(
            state.user_query or ""
        ),
    )
    deadline_update = {}
    try:
        if state.run_deadline is not None:
            observed, observation = observe_run_deadline(state.run_deadline)
            deadline_update["run_deadline"] = observed
            if observation.phase == "expired":
                raise ValueError(
                    "delivery deadline elapsed before itinerary composition"
                )
        if state.recommendation_catalog is None:
            raise ValueError("composition requires an admitted Recommendation Catalog")
        if phase == "placement_skeleton":
            draft = await _compose_draft(
                state,
                str(assignment["objective"]),
                llm_for_task(get_model_router(), TaskKind.COMPOSITION),
                required_kinds,
                required_legs,
                unlocatable,
            )
            from travel_agent.services.state_invalidation import (
                workspace_acceptance_invalidation,
            )

            return {
                **deadline_update,
                **workspace_acceptance_invalidation(),
                "messages": [AIMessage(content="完整行程草稿已完成，接着核对相邻路线")],
                "agent_status": {output_key: "pending"},
                "placement_skeleton": draft,
                "trip_workspace_v2": None,
                "local_connector_gaps": [],
                "candidate_gate_status": "needs_research",
                "candidate_gate_route": "candidate_gate",
                "unlocatable_authored_places": sorted(unlocatable),
                "composition_failure_context": None,
                "placement_skeleton_failure_context": None,
            }
        if state.candidate_gate_status != "passed":
            raise ValueError("connector materialization requires a passed Gate")
        skeleton = state.placement_skeleton
        requests, required_pairs = connector_mode_requests_from_constraint_pack(
            skeleton,
            state.constraint_pack,
            state.recommendation_catalog,
        )
        gaps = extract_local_connector_gaps(
            skeleton,
            state.recommendation_catalog,
            weather_data_revision=state.recommendation_catalog.weather_data_revision,
            flexible_mode_requests=requests,
            required_flexible_mode_pairs=required_pairs,
            default_walk_day_ids=default_walking_days(state, skeleton),
            required_candidate_kinds=required_kinds,
        )
        unfilled = unfilled_connector_gaps(state.recommendation_catalog, gaps)
        authored = (
            await _author_connector_routes(
                llm_for_task(get_model_router(), TaskKind.COMPOSITION),
                unfilled,
            )
            if unfilled
            else {}
        )
        composition = materialize_skeleton_connectors(
            skeleton,
            state.recommendation_catalog,
            gaps,
            authored,
            required_candidate_kinds=required_kinds,
            required_long_distance_legs=required_legs,
            required_leg_scope_ids=_required_leg_scope_ids(
                required_legs,
                state.run_id,
                state.constraint_pack_revision,
            ),
        )
        stage = "materialize_connectors/workspace_materialization"
        workspace = materialize_trip_workspace(
            run_id=state.run_id,
            workspace_revision=0,
            composition=composition,
            catalog=catalog_for_workspace_materialization(
                full_catalog, state.candidate_selection_plan
            ),
            intent_contract_snapshot=IntentContractSnapshot.from_intent_spec(
                state.intent_spec
            ),
            candidate_selection_plan=state.candidate_selection_plan,
            composition_mutations=list(state.composition_mutations),
            user_input_anchors=_draft_user_input_anchors(state),
            reference_services=list(state.provider_reference_services),
            required_candidate_kinds=required_kinds,
            required_long_distance_legs=required_legs,
            required_leg_scope_ids=_required_leg_scope_ids(
                required_legs,
                state.run_id,
                state.constraint_pack_revision,
            ),
        )
        workspace = _restore_full_catalog(workspace, full_catalog)
        workspace = apply_day_design(workspace, composition)
        workspace = disclose_default_walking(workspace, gaps)
        _log_composition_dispersion(workspace)
        return {
            **deadline_update,
            "messages": [AIMessage(content="精确相邻路线已物化为正式行程")],
            "agent_status": {output_key: "completed"},
            "trip_workspace_v2": workspace,
            "recommendation_catalog": workspace.recommendation_catalog,
            "local_connector_gaps": gaps,
            "unlocatable_authored_places": sorted(unlocatable),
            "composition_failure_context": None,
            "placement_skeleton_failure_context": None,
        }
    except Exception as exc:
        logger.error("ItineraryPlanner v2 failed: %s", exc, exc_info=True)
        return {
            **deadline_update,
            "messages": [AIMessage(content="行程草稿需要修订")],
            "last_error": str(exc),
            "agent_status": {output_key: "failed"},
            "unlocatable_authored_places": sorted(unlocatable),
            "composition_failure_context": bounded_repair_context(
                stage, _composition_failure_detail(exc)
            ),
            **(
                {"placement_skeleton": exc.composition}
                if getattr(exc, "composition", None) is not None
                else {}
            ),
        }
