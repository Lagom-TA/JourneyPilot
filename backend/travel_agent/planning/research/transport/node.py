from __future__ import annotations

import datetime
import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from travel_agent.conversation.history import append_recent_history
from travel_agent.llm.router import get_model_router
from travel_agent.llm.task_routing import TaskKind, llm_for_task, plain_observation_messages
from travel_agent.memory.research_context import format_worker_research_context
from travel_agent.planning.assignments import (
    assignment_research_round,
    resolve_agent_assignment,
)
from travel_agent.planning.invalidation import generation_packet_key
from travel_agent.planning.requirements.constraint_applicability import (
    active_hard_constraint_ids,
)
from travel_agent.planning.research.assignment_context import build_assignment_context
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.errors import format_worker_last_error
from travel_agent.planning.research.output.failures import (
    build_failure_only_research_packet,
    provider_round_answered_empty,
    provider_round_capability_declared,
)
from travel_agent.planning.research.output.finalization import (
    parse_research_packet,
)
from travel_agent.planning.research.output.metadata import (
    build_authoritative_research_packet_metadata,
)
from travel_agent.planning.research.output.options import provider_evidence_outcomes
from travel_agent.planning.research.output.policy import packet_candidate_limit
from travel_agent.planning.research.output.transcript import authoritative_tool_messages
from travel_agent.planning.research.prompts import build_research_packet_prompt
from travel_agent.planning.research.query_contracts import ResearchQueryKind
from travel_agent.planning.research.query_planner import queries_by_ids
from travel_agent.planning.research.reference_service_contracts import (
    ProviderReferenceService,
)
from travel_agent.planning.research.transport.prompts import build_transport_task_prompt
from travel_agent.planning.research.transport.rail.binding import (
    discover_domestic_rail_route,
)
from travel_agent.planning.research.transport.scope import (
    _NODE_NAME,
    constrain_cross_day_flight_tools,
    scope_initial_transport_tools,
    scope_long_distance_transport_tools,
    transport_provider_assignments,
)
from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.tool_context import build_tool_context_from_state
from travel_agent.runtime.cancellation import RunCancelled
from travel_agent.storage.worker_journal_store import JournalConflict
from travel_agent.tools.access import (
    exclude_tools,
    filter_tools_for_agent,
    get_available_tools,
)
from travel_agent.tools.react import streaming_react_loop

if TYPE_CHECKING:
    from travel_agent.runtime.events import EventBuffer


logger = logging.getLogger(__name__)


_LAST_ERROR_LOG_LIMIT = 600


_MAX_TOOL_ITERATIONS = 5


async def transport_researcher_node(
    state: TravelAgentState, config: RunnableConfig
) -> Dict[str, Any]:
    """交通研究员节点：查询强类型多段交通候选并输出 Research Packet。"""
    router = get_model_router()
    llm = llm_for_task(router, TaskKind.RESEARCH_TOOLS, has_tools=True)
    stream_queue: Optional["EventBuffer"] = config.get("configurable", {}).get(
        "stream_queue"
    )

    current_time = state.current_time or datetime.datetime.now().strftime(
        "%Y-%m-%d %H:%M"
    )
    user_query = state.user_query or ""
    run_id = state.run_id

    output_key, assignment = resolve_agent_assignment(
        state.agent_assignments or {}, _NODE_NAME
    )
    research_brief_context = build_assignment_context(
        assignment=assignment,
        brief=state.research_brief,
        intent_spec=state.intent_spec,
        constraint_pack=state.constraint_pack,
    )
    task_desc = assignment["objective"]
    if state.research_query_plan is None:
        raise ValueError("transport research requires a Research Query Plan")
    planned_queries = [
        query
        for query in queries_by_ids(
            state.research_query_plan,
            assignment.get("research_query_ids") or [],
        )
        if query.domain
        in {
            ResearchDomain.LOCAL_TRANSPORT,
            ResearchDomain.LONG_DISTANCE_TRANSPORT,
        }
    ]
    task_desc = (
        f"{task_desc}；研究查询："
        + "；".join(query.query_text for query in planned_queries)
    )[:1000]
    recommended_tools = assignment.get("recommended_tools", [])
    excluded_tools = assignment.get("excluded_tools", [])
    provider_assignments = transport_provider_assignments(assignment, state)
    required_route_scopes = [
        item.scope for item in provider_assignments if item.scope.route_leg is not None
    ]

    if state.planning_generation is None:
        raise ValueError("transport research requires a planning generation")
    generation_id = state.planning_generation.generation_id
    upstream_packet_context = format_worker_research_context(
        state.research_packets,
        worker_kind=_NODE_NAME,
        run_id=run_id,
        generation_id=generation_id,
        planned_queries=planned_queries,
        assignment=assignment,
    )

    active_constraint_ids = active_hard_constraint_ids(
        state.constraint_pack,
        worker_kind=_NODE_NAME,
    )
    prompt = build_research_packet_prompt(
        worker_kind=_NODE_NAME,
        run_id=run_id,
        task_id=output_key,
        constraint_pack_revision=state.constraint_pack_revision,
        fact_data_revision=state.fact_data_revision,
        current_time=current_time,
        research_brief_context=research_brief_context,
        candidate_limit=packet_candidate_limit(
            _NODE_NAME,
            required_route_scopes=required_route_scopes,
        ),
        upstream_packet_context=upstream_packet_context,
        active_constraint_ids=active_constraint_ids,
        state=state,
        recommended_tools=recommended_tools,
    )

    logger.info(
        "TransportResearcher 上下文注入: anchor=%s, preset=%s, district_ctx_len=%d",
        bool(state.session_anchor),
        bool(state.preset_context),
        len(upstream_packet_context),
    )

    history: List[Dict[str, Any]] = []
    append_recent_history(history, state)
    messages = prompt.messages(history)
    messages.append(
        {
            "role": "user",
            "content": build_transport_task_prompt(
                task_desc=task_desc,
                user_query=user_query,
                required_route_scopes=required_route_scopes,
            ),
        }
    )

    available_tools = await get_available_tools(state.selected_mcp_servers or [])
    available_tools = filter_tools_for_agent(available_tools, _NODE_NAME)
    available_tools = exclude_tools(available_tools, excluded_tools)
    available_tools = scope_initial_transport_tools(available_tools)
    available_tools = scope_long_distance_transport_tools(
        available_tools,
        controlled_trip_identity=state.controlled_trip_identity,
    )
    cross_day_required = bool(required_route_scopes) and all(
        scope.route_leg is not None and scope.route_leg.cross_day_required
        for scope in required_route_scopes
    )
    available_tools = constrain_cross_day_flight_tools(
        available_tools,
        required=cross_day_required,
    )

    tool_cache = dict(state.tool_cache) if state.tool_cache else {}
    tool_context = build_tool_context_from_state(state)
    executed_queries = [
        query.model_dump(mode="json")
        for query in planned_queries
        if query.query_kind
        in {
            ResearchQueryKind.INTENT_PRIMARY,
            ResearchQueryKind.STRUCTURAL,
            ResearchQueryKind.TARGETED_REPAIR,
        }
    ]
    packet_state_key = generation_packet_key(output_key, generation_id)
    authoritative_packet_metadata = build_authoritative_research_packet_metadata(
        worker_kind=_NODE_NAME,
        run_id=run_id,
        generation_id=generation_id,
        intent_spec_revision=state.intent_spec_revision,
        research_query_plan_id=state.research_query_plan.query_plan_id,
        executed_queries=executed_queries,
        task_id=output_key,
        constraint_pack_revision=state.constraint_pack_revision,
        fact_data_revision=state.fact_data_revision,
        query_context={
            "objective": task_desc,
            "controlled_trip_identity": state.controlled_trip_identity or {},
            "required_route_legs": [
                scope.route_leg.model_dump(mode="json")
                for scope in required_route_scopes
                if scope.route_leg is not None
            ],
            "research_round": assignment_research_round(output_key),
        },
        generated_at=datetime.datetime.now(datetime.timezone.utc),
    )

    authoritative_tool_results: List[Dict[str, Any]] = []

    reference_services: List[ProviderReferenceService] = []

    finalize_started_at: Optional[float] = None
    try:
        await discover_domestic_rail_route(
            state=state,
            messages=messages,
            required_transport_classes=None,
            connector_gaps=None,
            tool_context=tool_context,
            authoritative_tool_results=authoritative_tool_results,
            reference_services=reference_services,
            required_route_scopes=required_route_scopes,
        )
        react = await streaming_react_loop(
            llm=llm,
            messages=messages,
            available_tools=available_tools,
            stream_queue=stream_queue,
            node_name=_NODE_NAME,
            max_iterations=_MAX_TOOL_ITERATIONS,
            can_ask_user=False,
            tool_cache=tool_cache,
            tool_context=tool_context,
        )
        raw_response = react.content
        if not raw_response.strip():
            # 工具循环没有产出正文时，用同一上下文做一次不带工具的直接生成。
            raw_response = await llm.ainvoke(
                plain_observation_messages(messages),
                response_format={"type": "json_object"},
            )
        authoritative_tool_results.extend(react.tool_results)

        finalize_started_at = time.perf_counter()
        packet = await parse_research_packet(
            raw_response or "",
            expected_worker=_NODE_NAME,
            expected_run_id=run_id,
            authoritative_tool_results=authoritative_tool_results,
            expected_active_constraint_ids=active_constraint_ids,
            authoritative_packet_metadata=authoritative_packet_metadata,
        )

        logger.info(
            "TransportResearcher 完成，key=%s candidates=%d facts=%d sources=%d finalize_ms=%.0f",
            output_key,
            len(packet.candidates),
            len(packet.fact_assertions),
            len(packet.source_records),
            (time.perf_counter() - finalize_started_at) * 1000.0,
        )

        return {
            "messages": [
                AIMessage(content=f"已整理 {len(packet.candidates)} 个交通候选")
            ],
            "research_packets": {packet_state_key: packet},
            "agent_status": {output_key: "completed"},
            "tool_cache": tool_cache,
            "provider_evidence_outcomes": provider_evidence_outcomes(
                authoritative_tool_messages(authoritative_tool_results),
                expected_worker=_NODE_NAME,
                packet=packet,
                assignments=provider_assignments,
            ),
            "provider_reference_services": reference_services,
        }

    except (RunCancelled, JournalConflict):
        raise
    except Exception as e:
        if finalize_started_at is not None:
            logger.info(
                "TransportResearcher 交付定型中断，key=%s finalize_ms=%.0f",
                output_key,
                (time.perf_counter() - finalize_started_at) * 1000.0,
            )
        evidence_messages = authoritative_tool_messages(authoritative_tool_results)
        failure_packet = build_failure_only_research_packet(
            authoritative_packet_metadata=authoritative_packet_metadata,
            context_messages=evidence_messages,
        )
        outcomes = provider_evidence_outcomes(
            evidence_messages,
            expected_worker=_NODE_NAME,
            packet=failure_packet,
            assignments=provider_assignments,
        )

        last_error = format_worker_last_error(
            e,
            provider_empty_round=provider_round_answered_empty(
                evidence_messages, outcomes=outcomes
            ),
            provider_capability_round=provider_round_capability_declared(
                evidence_messages, outcomes=outcomes
            ),
        )
        logger.error(
            "TransportResearcher 执行失败: worker=%s key=%s last_error=%s",
            _NODE_NAME,
            output_key,
            last_error[:_LAST_ERROR_LOG_LIMIT],
        )
        result = {
            "messages": [AIMessage(content="交通 Research Packet 生成失败")],
            "last_error": last_error,
            "agent_status": {output_key: "failed"},
        }
        if failure_packet is not None:
            result["research_packets"] = {packet_state_key: failure_packet}
        result["provider_evidence_outcomes"] = outcomes

        if reference_services:
            result["provider_reference_services"] = reference_services
        return result
