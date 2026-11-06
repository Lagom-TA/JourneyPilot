from __future__ import annotations

import datetime
import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from travel_agent.config.loader import get_settings
from travel_agent.knowledge.collections import grounding_corpus
from travel_agent.knowledge.source_records import rag_chunk_source_records
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
from travel_agent.planning.research.destination.diagnostics import _log_rag_place_funnel
from travel_agent.planning.research.destination.scope import _NODE_NAME
from travel_agent.planning.research.errors import format_worker_last_error
from travel_agent.planning.research.feedback import append_research_redo_messages
from travel_agent.planning.research.output.failures import (
    build_failure_only_research_packet,
    provider_round_answered_empty,
    provider_round_capability_declared,
)
from travel_agent.planning.research.output.finalization import (
    parse_research_packet_or_reask,
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
)
from travel_agent.tools.react import streaming_react_loop
from travel_agent.tools.result import ReactOutcome

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
    run_id = state.run_id

    output_key, assignment = resolve_agent_assignment(
        state.agent_assignments or {}, _NODE_NAME
    )
    task_desc = assignment["objective"]
    recommended_tools = assignment.get("recommended_tools", [])
    excluded_tools = assignment.get("excluded_tools", [])
    provider_assignments = parse_provider_evidence_assignments(
        assignment,
        expected_worker=_NODE_NAME,
        expected_run_id=run_id,
    )

    if state.planning_generation is None:
        raise ValueError("destination research requires a planning generation")
    generation_id = state.planning_generation.generation_id
    upstream_packet_context = format_worker_research_context(
        state.research_packets,
        worker_kind=_NODE_NAME,
        run_id=run_id,
        generation_id=generation_id,
        fact_data_revision=state.fact_data_revision,
        destination_ids=[item.get("place_id", "") for item in state.controlled_trip_identity.get("destinations", [])],
    )

    active_constraint_ids = active_hard_constraint_ids(
        state.constraint_pack,
        worker_kind=_NODE_NAME,
    )
    prompt = build_research_packet_prompt(
        worker_kind=_NODE_NAME,
        run_id=run_id,
        task_id=output_key,
        fact_data_revision=state.fact_data_revision,
        current_time=current_time,
        candidate_limit=packet_candidate_limit(
            _NODE_NAME, trip_identity=state.controlled_trip_identity
        ),
        task_desc=task_desc,
        upstream_packet_context=upstream_packet_context,
        active_constraint_ids=active_constraint_ids,
        state=state,
        recommended_tools=recommended_tools,
    )

    logger.info(
        "DestinationResearcher 旅行理解=%s, knowledge=%s",
        bool(state.current_requirements),
        "on_demand" if get_settings().embedding.enabled else "disabled",
    )

    messages = prompt.messages()

    available_tools = await get_available_tools()
    available_tools = filter_tools_for_agent(available_tools, _NODE_NAME)
    available_tools = exclude_tools(available_tools, excluded_tools)

    tool_cache = dict(state.tool_cache) if state.tool_cache else {}
    tool_context = build_tool_context_from_state(state)
    packet_state_key = generation_packet_key(output_key, generation_id)
    authoritative_packet_metadata = build_authoritative_research_packet_metadata(
        worker_kind=_NODE_NAME,
        run_id=run_id,
        generation_id=generation_id,
        task_id=output_key,
        fact_data_revision=state.fact_data_revision,
        query_context={
            "objective": task_desc,
            "controlled_trip_identity": state.controlled_trip_identity or {},
            "research_round": assignment_research_round(output_key),
        },
        generated_at=datetime.datetime.now(datetime.timezone.utc),
    )

    authoritative_tool_results: List[Dict[str, Any]] = []

    finalize_started_at: Optional[float] = None
    redo_requests_update: Optional[Dict[str, Any]] = None
    try:
        redo_requests_update = append_research_redo_messages(
            state=state,
            messages=messages,
            worker_base=_NODE_NAME,
            output_key=output_key,
        )

        react = await streaming_react_loop(
            llm=llm,
            messages=messages,
            available_tools=available_tools,
            stream_queue=stream_queue,
            # 返研轮的事件带轮次标识，工作台能区分重做与首轮研究。
            node_name=(
                output_key
                if assignment_research_round(output_key) > 0
                else _NODE_NAME
            ),
            max_iterations=_MAX_TOOL_ITERATIONS,
            can_ask_user=False,
            tool_cache=tool_cache,
            tool_context=tool_context,
            public_note=True,
        )
        authoritative_tool_results.extend(react.tool_results)
        if react.outcome is ReactOutcome.ITERATION_LIMIT:
            raw_response = await llm.ainvoke(
                plain_observation_messages(messages),
                response_format={"type": "json_object"},
            )
        elif react.outcome is ReactOutcome.FINAL_ANSWER:
            raw_response = react.content
        else:
            raise RuntimeError(f"研究未完成: {react.error or react.outcome.value}")

        finalize_started_at = time.perf_counter()
        packet = await parse_research_packet_or_reask(
            raw_response or "",
            llm=llm,
            messages=messages,
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

        outcomes = provider_evidence_outcomes(
            authoritative_tool_messages(authoritative_tool_results),
            expected_worker=_NODE_NAME,
            packet=packet,
            assignments=provider_assignments,
        )
        return {
            "messages": [
                AIMessage(content=f"已整理 {len(packet.candidates)} 个目的地候选")
            ],
            "research_packets": {packet_state_key: packet},
            "agent_status": {output_key: "completed"},
            "tool_cache": tool_cache,
            **({"provider_evidence_outcomes": outcomes} if outcomes else {}),
            **(
                {"research_redo_requests": redo_requests_update}
                if redo_requests_update is not None
                else {}
            ),
        }

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
        if outcomes:
            result["provider_evidence_outcomes"] = outcomes
        return result
