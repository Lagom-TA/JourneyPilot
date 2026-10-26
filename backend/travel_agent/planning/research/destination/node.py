from __future__ import annotations

import datetime
import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from travel_agent.config.loader import get_settings
from travel_agent.conversation.history import append_recent_history
from travel_agent.knowledge.collections import grounding_corpus
from travel_agent.knowledge.source_records import rag_chunk_source_records
from travel_agent.llm.router import get_model_router
from travel_agent.llm.task_routing import TaskKind, llm_for_task
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
from travel_agent.planning.research.destination.diagnostics import _log_rag_place_funnel
from travel_agent.planning.research.destination.discovery import (
    discover_and_resolve_required_places,
)
from travel_agent.planning.research.destination.operating_information import (
    collect_place_operating_information,
)
from travel_agent.planning.research.destination.scope import (
    _NODE_NAME,
    _SCOPED_DISCOVERY_TOOLS,
    build_destination_boundaries,
    build_destination_task_prompt,
    collect_offered_dining_place_ids,
    resolve_discovery_candidate_kinds,
)
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
from travel_agent.planning.research.output.options import (
    provider_evidence_outcomes,
)
from travel_agent.planning.research.output.policy import packet_candidate_limit
from travel_agent.planning.research.output.transcript import authoritative_tool_messages
from travel_agent.planning.research.prompts import build_research_packet_prompt
from travel_agent.planning.research.provider_assignments import (
    parse_provider_evidence_assignments,
)
from travel_agent.planning.research.query_planner import queries_by_ids
from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.tool_context import build_tool_context_from_state
from travel_agent.runtime.cancellation import RunCancelled
from travel_agent.storage.worker_journal_store import JournalConflict
from travel_agent.tools.access import (
    exclude_tools,
    filter_tools_for_agent,
    get_available_tools,
)
from travel_agent.tools.knowledge_results import (
    knowledge_tool_documents,
    knowledge_tool_summaries,
)
from travel_agent.tools.react import streaming_react_loop

if TYPE_CHECKING:
    from travel_agent.runtime.events import EventBuffer


logger = logging.getLogger(__name__)


_LAST_ERROR_LOG_LIMIT = 600


_MAX_TOOL_ITERATIONS = 3


async def destination_researcher_node(
    state: TravelAgentState, config: RunnableConfig
) -> Dict[str, Any]:
    """目的地研究员节点：收集具体 Visit/Dining 候选并输出 Research Packet。"""
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
        raise ValueError("destination research requires a Research Query Plan")
    planned_queries = queries_by_ids(
        state.research_query_plan,
        assignment.get("research_query_ids") or [],
    )
    planned_queries = [
        query
        for query in planned_queries
        if query.domain in {ResearchDomain.VISIT, ResearchDomain.DINING}
    ]
    recommended_tools = assignment.get("recommended_tools", [])
    excluded_tools = assignment.get("excluded_tools", [])
    required_candidate_kinds = assignment.get("required_candidate_kinds")
    provider_assignments = parse_provider_evidence_assignments(
        assignment,
        expected_worker=_NODE_NAME,
        expected_run_id=run_id,
        expected_constraint_pack_revision=state.constraint_pack_revision,
    )

    if state.planning_generation is None:
        raise ValueError("destination research requires a planning generation")
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
        candidate_limit=packet_candidate_limit(_NODE_NAME),
        upstream_packet_context=upstream_packet_context,
        active_constraint_ids=active_constraint_ids,
        state=state,
        recommended_tools=recommended_tools,
    )

    logger.info(
        "DestinationResearcher 上下文注入: constraint_pack=%s, anchor=%s, preset=%s, knowledge=%s",
        bool(state.constraint_pack),
        bool(state.session_anchor),
        bool(state.preset_context),
        "on_demand" if get_settings().embedding.enabled else "disabled",
    )

    history: List[Dict[str, Any]] = []
    append_recent_history(history, state)
    messages = prompt.messages(history)
    destination_boundaries = build_destination_boundaries(
        state.controlled_trip_identity
    )

    available_tools = await get_available_tools(state.selected_mcp_servers or [])
    available_tools = filter_tools_for_agent(available_tools, _NODE_NAME)
    available_tools = exclude_tools(available_tools, excluded_tools)

    tool_cache = dict(state.tool_cache) if state.tool_cache else {}
    tool_context = build_tool_context_from_state(state)
    executed_query_ids: List[str] = []
    executed_queries = [
        query.model_dump(mode="json")
        for query in planned_queries
        if query.query_id in set(executed_query_ids)
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
            "research_round": assignment_research_round(output_key),
        },
        generated_at=datetime.datetime.now(datetime.timezone.utc),
    )

    discovery_candidate_kinds = resolve_discovery_candidate_kinds(
        required_candidate_kinds,
        task_desc=str(task_desc or ""),
        user_query=user_query,
        controlled_trip_identity=state.controlled_trip_identity or {},
    )

    authoritative_tool_results: List[Dict[str, Any]] = []

    finalize_started_at: Optional[float] = None
    try:
        preflight_messages: List[Dict[str, Any]] = []
        if discovery_candidate_kinds:
            await discover_and_resolve_required_places(
                messages=preflight_messages,
                available_tools=available_tools,
                required_candidate_kinds=discovery_candidate_kinds,
                destination_boundaries=destination_boundaries,
                tool_context=tool_context,
                authoritative_tool_results=authoritative_tool_results,
                planned_queries=planned_queries,
                executed_query_ids=executed_query_ids,
            )
        authoritative_packet_metadata["executed_query_ids"] = list(
            dict.fromkeys(executed_query_ids)
        )
        authoritative_packet_metadata["query_context"]["query_lineage"] = [
            query.model_dump(mode="json")
            for query in planned_queries
            if query.query_id in set(executed_query_ids)
        ]
        messages.append(
            {
                "role": "user",
                "content": build_destination_task_prompt(
                    task_desc=task_desc,
                    user_query=user_query,
                    rag_context_section="",
                    offered_dining_place_ids=collect_offered_dining_place_ids(
                        authoritative_tool_results
                    ),
                    destination_boundaries=destination_boundaries,
                ),
            }
        )
        messages.extend(preflight_messages)
        discovery_tools = [
            name
            for name in _SCOPED_DISCOVERY_TOOLS
            if any(
                tool.get("schema", {}).get("function", {}).get("name") == name
                for tool in available_tools
            )
        ]
        messages.append(
            {
                "role": "user",
                "content": (
                    "发现与身份解析分两步：先从本轮知识库或刚注入的探索结果中提名具体地点，再用原名调用 global_place_search，必要时只补城市名。"
                    "不要把主题、区域体验、旅游线路或类别探索句送入名称解析。网页结果只支持名称提名及其实际内容，不支持place_id。"
                    "先利用已有探索结果并核实具体地点，避免重复检索同一主题；按用户原意研究区域体验，不默认限定为博物馆。"
                    f"本轮已注册的网页工具：{', '.join(discovery_tools) or '无'}。"
                    "只能激活本轮目录中真实存在的工具，不反复查找search_web/tavily/brave等未注册名称。"
                    "网页工具缺失时可用现有知识库提名；仅在目录有maps_text_search且目的地在中国时，可用其类别关键词能力发现地点。"
                ),
            }
        )

        react = await streaming_react_loop(
            llm=llm,
            messages=messages,
            available_tools=available_tools,
            stream_queue=stream_queue,
            node_name=_NODE_NAME,
            max_iterations=_MAX_TOOL_ITERATIONS,
            can_ask_user=True,
            tool_cache=tool_cache,
            tool_context=tool_context,
        )
        raw_response = react.content
        pending_choice = react.pending_choice
        authoritative_tool_results.extend(react.tool_results)

        if pending_choice:
            logger.info(
                "DestinationResearcher 触发 ask_user: %s",
                (pending_choice.get("question") or "")[:60],
            )
            return {
                "messages": [
                    AIMessage(
                        content=pending_choice.get("question")
                        or "需要用户澄清目的地信息"
                    )
                ],
                "pending_user_choice": {
                    "questions": [
                        {
                            "question": pending_choice.get("question", ""),
                            "options": pending_choice.get("options", []),
                            "selection_type": pending_choice.get(
                                "selection_type", "single"
                            ),
                        }
                    ],
                    "round": 1,
                    "allow_free_input": pending_choice.get("allow_free_input", True),
                },
                "agent_status": {output_key: "partial"},
                "next_agent": "HALT",
            }

        finalize_started_at = time.perf_counter()
        await collect_place_operating_information(
            available_tools=available_tools,
            tool_context=tool_context,
            authoritative_tool_results=authoritative_tool_results,
            messages=messages,
        )
        packet = await parse_research_packet(
            raw_response or "",
            expected_worker=_NODE_NAME,
            expected_run_id=run_id,
            authoritative_tool_results=authoritative_tool_results,
            expected_active_constraint_ids=active_constraint_ids,
            authoritative_packet_metadata=authoritative_packet_metadata,
        )

        logger.info(
            "DestinationResearcher 完成，key=%s candidates=%d facts=%d sources=%d finalize_ms=%.0f",
            output_key,
            len(packet.candidates),
            len(packet.fact_assertions),
            len(packet.source_records),
            (time.perf_counter() - finalize_started_at) * 1000.0,
        )
        rag_docs = knowledge_tool_documents(authoritative_tool_results)
        if any(
            env.get("tool_name") == "knowledge_search"
            for env in authoritative_tool_results
        ):
            _log_rag_place_funnel(
                rag_chunk_source_records(rag_docs),
                authoritative_tool_results=authoritative_tool_results,
                candidates=packet.candidates,
                corpus=grounding_corpus(),
            )

        result: Dict[str, Any] = {
            "messages": [
                AIMessage(content=f"已整理 {len(packet.candidates)} 个目的地候选")
            ],
            "research_packets": {packet_state_key: packet},
            "agent_status": {output_key: "completed"},
            "retrieved_docs": rag_docs,
            "retrieval_summaries": knowledge_tool_summaries(authoritative_tool_results),
            "tool_cache": tool_cache,
            "provider_evidence_outcomes": provider_evidence_outcomes(
                authoritative_tool_messages(authoritative_tool_results),
                expected_worker=_NODE_NAME,
                packet=packet,
                assignments=provider_assignments,
            ),
        }
        return result

    except (RunCancelled, JournalConflict):
        raise
    except Exception as e:
        if finalize_started_at is not None:
            logger.info(
                "DestinationResearcher 交付定型中断，key=%s finalize_ms=%.0f",
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
            "DestinationResearcher 执行失败: worker=%s key=%s last_error=%s",
            _NODE_NAME,
            output_key,
            last_error[:_LAST_ERROR_LOG_LIMIT],
        )
        result = {
            "messages": [AIMessage(content="目的地 Research Packet 生成失败")],
            "last_error": last_error,
            "agent_status": {output_key: "failed"},
        }
        if failure_packet is not None:
            result["research_packets"] = {packet_state_key: failure_packet}
        result["provider_evidence_outcomes"] = outcomes
        return result
