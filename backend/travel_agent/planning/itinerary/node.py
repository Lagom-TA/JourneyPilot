from __future__ import annotations

import logging
from typing import Any, Dict

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.tool_context import build_tool_context_from_state
from travel_agent.llm.router import get_model_router
from travel_agent.llm.task_routing import TaskKind, llm_for_task
from travel_agent.planning.assignments import resolve_agent_assignment
from travel_agent.planning.itinerary.composition import _compose_draft
from travel_agent.planning.research.feedback import (
    RESEARCH_REDO_ROUNDS_CAP,
    ResearchRedoRequest,
    build_research_redo_request,
    latest_worker_packet,
    redo_assignment_key,
)
from travel_agent.planning.itinerary.connectors import (
    connector_mode_requests_from_constraint_pack,
    extract_local_connector_gaps,
    materialize_skeleton_connectors,
    overtimed_connector_gaps,
    unfilled_connector_gaps,
)
from travel_agent.planning.itinerary.locations import locate_authored_composition
from travel_agent.planning.itinerary.materialize import materialize_trip_workspace
from travel_agent.planning.itinerary.rail_paths import complete_rail_route_paths
from travel_agent.planning.itinerary.requirements import _draft_user_input_anchors
from travel_agent.planning.itinerary.title_writing import write_itinerary_copy
from travel_agent.planning.nodes import NODE_ITINERARY
from travel_agent.planning.workspace import TripWorkspace
from travel_agent.runtime.deadlines import observe_run_deadline
from travel_agent.runtime.cancellation import RunCancelled
from travel_agent.storage.worker_journal_store import JournalConflict
from travel_agent.tools.access import filter_tools_for_agent, get_available_tools
from travel_agent.planning.itinerary.day_design import apply_day_design
from travel_agent.planning.itinerary.dispersion import itinerary_dispersion
from travel_agent.planning.research.transport.followup import research_transport_followup

logger = logging.getLogger(__name__)


# 失败摘要进入一次重试的提示词，超过这个长度的细节被截断。
_FAILURE_CONTEXT_CHAR_LIMIT = 600

# 实际路线超出可用时间窗时，允许重新组合以调整排程的最大次数。
_COMPOSITION_RESCHEDULE_LIMIT = 1


def _log_composition_dispersion(workspace: TripWorkspace) -> None:
    """记录每天接驳分钟数与停留点跨度，便于排查排程异常。"""
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


def _composition_failure_context(stage: str, exc: BaseException) -> str:
    """把失败阶段与异常摘要压成一行，供一次重试的提示词使用。"""
    text = f"{stage} 阶段失败 — {type(exc).__name__}: {exc}".strip()
    if len(text) <= _FAILURE_CONTEXT_CHAR_LIMIT:
        return text
    return text[: _FAILURE_CONTEXT_CHAR_LIMIT - 1] + "…"


def _connector_overtime_context(
    overtimed: list[tuple[Any, int, int]],
    response: dict[str, Any] | None = None,
) -> str:
    """将超出时间窗的相邻路段整理为提示，供下一轮行程组合修正。"""
    parts = [
        f"{gap.day_date} "
        f"{gap.from_endpoint.name if gap.from_endpoint else gap.from_place_id}→"
        f"{gap.to_endpoint.name if gap.to_endpoint else gap.to_place_id}，"
        f"{gap.departure_time:%H:%M} 出发至 {gap.latest_arrival_time:%H:%M} 抵达，"
        f"路线约 {duration} 分钟、可用窗口 {window} 分钟"
        for gap, duration, window in overtimed
    ]
    payload = (response or {}).get("sanitized_result")
    response_text = str(payload.get("summary") or "") if isinstance(payload, dict) else ""
    prefix = (
        "交通研究员补查结果：" + response_text + "。相邻停留点的实际路线超出可用时间窗口："
        if response is not None
        else "上一轮相邻停留点的路线耗时超出可用时间窗口："
    )
    text = (
        prefix
        + "；".join(parts)
        + "。请调整停留时间或改用更近的候选，为门到门接驳留出足够时间。"
    )
    if len(text) <= _FAILURE_CONTEXT_CHAR_LIMIT:
        return text
    return text[: _FAILURE_CONTEXT_CHAR_LIMIT - 1] + "…"


def _composition_phase(state: TravelAgentState) -> str:
    """本次调用生成草稿，还是把已有草稿物化为正式行程。"""
    if (
        state.placement_skeleton is None
        or state.trip_workspace is not None
        or state.composition_failure_context is not None
    ):
        return "placement_skeleton"
    return "materialize_connectors"


def _research_redo_update(
    state: TravelAgentState,
    request: ResearchRedoRequest,
    output_key: str,
    deadline_update: Dict[str, Any],
) -> Dict[str, Any]:
    """把组合的返研请求写成图状态更新，让图路由到对应 Worker 重做。

    返研轮的 assignment 带轮次后缀并续编 provider 证据尝试；组合自身回到
    待执行状态，Worker 完成后由 dispatcher 重建目录并再次进入组合。
    """
    base = request.worker_kind
    redo_rounds = dict(state.research_redo_rounds or {})
    previous_redos = redo_rounds.get(base, 0)
    if previous_redos >= RESEARCH_REDO_ROUNDS_CAP:
        raise ValueError(
            f"composition requested a redo of {base} beyond the allowed rounds"
        )
    prior = latest_worker_packet(state, base)
    prior_key = prior[0] if prior is not None else ""
    assignments = dict(state.agent_assignments or {})
    original = assignments.get(base)
    if not isinstance(original, dict):
        raise ValueError(f"composition redo requires the original assignment of {base}")
    next_round = previous_redos + 2
    from travel_agent.planning.research.plan import build_worker_assignment

    # agent_assignments 整体替换语义：更新必须携带完整字典。
    assignments[redo_assignment_key(base, next_round)] = build_worker_assignment(
        state, base, str(original["objective"])
    )
    return {
        **deadline_update,
        "messages": [
            AIMessage(
                content=(
                    f"行程安排无法基于当前{base}的成果完成，"
                    f"已要求其按反馈重做：{request.feedback[:200]}"
                )
            )
        ],
        "agent_status": {output_key: "pending"},
        "next_agent": base,
        "research_redo_requests": {
            **(state.research_redo_requests or {}),
            base: build_research_redo_request(
                worker_base=base,
                feedback=request.feedback,
                prior_packet_key=prior_key,
                next_round=next_round,
            ),
        },
        "research_redo_rounds": {**redo_rounds, base: previous_redos + 1},
        "agent_assignments": assignments,
        "placement_skeleton": None,
        "local_connector_gaps": [],
        "composition_failure_context": None,
    }


async def itinerary_planner_node(
    state: TravelAgentState, config: RunnableConfig
) -> Dict[str, Any]:
    output_key, assignment = resolve_agent_assignment(
        state.agent_assignments or {}, NODE_ITINERARY
    )
    phase = _composition_phase(state)
    stage = phase
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
            raise ValueError("composition requires the candidate catalog")
        if phase == "placement_skeleton":
            configurable = (config or {}).get("configurable", {})
            available_tools = filter_tools_for_agent(
                await get_available_tools(),
                NODE_ITINERARY,
            )
            catalog_updates = []
            result = await _compose_draft(
                state,
                str(assignment["objective"]),
                llm_for_task(get_model_router(), TaskKind.COMPOSITION, has_tools=True),
                available_tools=available_tools,
                tool_context=build_tool_context_from_state(state),
                stream_queue=configurable.get("stream_queue"),
                tool_cache=dict(state.tool_cache) if state.tool_cache else None,
                catalog_updates=catalog_updates,
            )
            catalog = catalog_updates[-1] if catalog_updates else state.recommendation_catalog
            if isinstance(result, ResearchRedoRequest):
                return {
                    **_research_redo_update(state, result, output_key, deadline_update),
                    "recommendation_catalog": catalog,
                }
            draft = result
            from travel_agent.planning.invalidation import workspace_acceptance_invalidation

            return {
                **deadline_update,
                **workspace_acceptance_invalidation(),
                "messages": [AIMessage(content="完整行程草稿已完成，接着核对相邻路线")],
                "agent_status": {output_key: "pending"},
                "next_agent": None,
                "placement_skeleton": draft,
                "recommendation_catalog": catalog,
                "trip_workspace": None,
                "local_connector_gaps": [],
                "composition_failure_context": None,
            }
        skeleton = await locate_authored_composition(state.placement_skeleton, state)
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
        )
        catalog = state.recommendation_catalog
        unfilled = unfilled_connector_gaps(catalog, gaps)
        response = None
        if unfilled:
            configurable = (config or {}).get("configurable", {})
            groups: dict[str, list] = {}
            for gap in unfilled:
                groups.setdefault(gap.destination_id, []).append(gap)
            for destination_id, destination_gaps in groups.items():
                response, catalog = await research_transport_followup(
                    state.model_copy(update={"placement_skeleton": skeleton, "recommendation_catalog": catalog}),
                    question="请查询这些相邻安排之间的市内接驳，说明可用路线和未能核实的部分。",
                    arrangement=skeleton.model_dump(mode="json"),
                    destination_id=destination_id,
                    gaps=destination_gaps,
                    stream_queue=configurable.get("stream_queue"),
                    request_id=f"skeleton_connectors:{destination_id}",
                )
            unfilled = unfilled_connector_gaps(catalog, gaps)
        composition = materialize_skeleton_connectors(skeleton, catalog, gaps, {})
        # 路线超出可用时间窗时，下一轮组合可按实际耗时调整排程。
        overtimed = overtimed_connector_gaps(catalog, gaps, {})
        if overtimed and (state.composition_reschedule_rounds or 0) < _COMPOSITION_RESCHEDULE_LIMIT:
            logger.info(
                "ItineraryPlanner 实际路线超出时间窗口，回炉修正排程: %s",
                [gap.gap_id for gap, _duration, _window in overtimed],
            )
            return {
                **deadline_update,
                "messages": [AIMessage(content="相邻路线与时间窗口冲突，正在重新安排")],
                "agent_status": {output_key: "pending"},
                "next_agent": None,
                "placement_skeleton": skeleton,
                "recommendation_catalog": catalog,
                "trip_workspace": None,
                "local_connector_gaps": [],
                "composition_reschedule_rounds": (
                    state.composition_reschedule_rounds or 0
                )
                + 1,
                "composition_failure_context": _connector_overtime_context(overtimed, response),
            }
        stage = "materialize_connectors/workspace_materialization"
        workspace = materialize_trip_workspace(
            run_id=state.run_id,
            workspace_revision=0,
            composition=composition,
            catalog=catalog,
            requirements=state.current_requirements,
            composition_mutations=list(state.composition_mutations),
            user_input_anchors=_draft_user_input_anchors(state),
            reference_services=list(state.provider_reference_services),
            connector_gaps=gaps,
        )
        workspace = await complete_rail_route_paths(
            workspace,
            tool_context=build_tool_context_from_state(state),
        )
        workspace = apply_day_design(workspace, composition)
        if unfilled:
            itinerary = workspace.itinerary
            unresolved = list(itinerary.unresolved)
            for gap in unfilled:
                origin = gap.from_endpoint.name if gap.from_endpoint else gap.from_place_id
                destination = gap.to_endpoint.name if gap.to_endpoint else gap.to_place_id
                unresolved.append(f"{gap.day_date.isoformat()} {origin}至{destination}的接驳尚未核实。")
            workspace = workspace.model_copy(update={
                "itinerary": itinerary.model_copy(update={"unresolved": list(dict.fromkeys(unresolved))})
            })
        try:
            workspace = await write_itinerary_copy(
                workspace,
                llm_for_task(get_model_router(), TaskKind.SUMMARY),
            )
        except (RunCancelled, JournalConflict):
            raise
        except Exception as exc:
            logger.warning("itinerary title writing unavailable: %s", exc)
        _log_composition_dispersion(workspace)
        return {
            **deadline_update,
                "messages": [AIMessage(content=(
                    "行程已整理，部分接驳仍待确认" if unfilled else "已根据路线整理正式行程"
                ))],
            "agent_status": {output_key: "completed"},
            "next_agent": None,
            "trip_workspace": workspace,
            "recommendation_catalog": workspace.recommendation_catalog,
            "local_connector_gaps": gaps,
            "composition_failure_context": None,
        }
    except (RunCancelled, JournalConflict):
        raise
    except Exception as exc:
        logger.error("ItineraryPlanner failed: %s", exc, exc_info=True)
        return {
            **deadline_update,
            "messages": [AIMessage(content="行程组合失败")],
            "last_error": str(exc),
            "agent_status": {output_key: "failed"},
            "next_agent": None,
            "composition_failure_context": _composition_failure_context(stage, exc),
        }
