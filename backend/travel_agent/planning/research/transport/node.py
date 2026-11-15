from __future__ import annotations

import datetime
import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

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
from travel_agent.planning.research.candidates import TransportCandidate
from travel_agent.planning.research.catalog import RecommendationCatalog
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
from travel_agent.planning.research.output.options import provider_evidence_outcomes
from travel_agent.planning.research.output.policy import packet_candidate_limit
from travel_agent.planning.research.output.sources import _remove_fact_references
from travel_agent.planning.research.output.transcript import authoritative_tool_messages
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.planning.research.prompts import build_research_packet_prompt
from travel_agent.planning.research.reference_service_contracts import (
    ProviderReferenceService,
)
from travel_agent.planning.research.transport.rail.binding import (
    discover_domestic_rail_route,
)
from travel_agent.planning.research.transport.rail.followup import compile_rail_followup_packet
from travel_agent.planning.research.transport.scope import (
    _NODE_NAME,
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
from travel_agent.tools.result import ReactOutcome

if TYPE_CHECKING:
    from travel_agent.runtime.events import EventBuffer


logger = logging.getLogger(__name__)


_LAST_ERROR_LOG_LIMIT = 600


_MAX_TOOL_ITERATIONS = 5


def _merge_initial_rail_packet(
    packet: ResearchPacket,
    rail: ResearchPacket,
    *,
    active_constraint_ids: List[str],
) -> ResearchPacket:
    """保留真实铁路候选，并合并模型已经提及的同一班次。"""
    payload = packet.model_dump(mode="python")
    rail_fields = {fact.field_path for fact in rail.fact_assertions}

    def replaces_rail_field(field_path: str) -> bool:
        return any(
            field_path == field or field_path.startswith((f"{field}.", f"{field}["))
            for field in rail_fields
        )

    for candidate in rail.candidates:
        existing = next(
            (
                item for item in packet.candidates
                if isinstance(item, TransportCandidate)
                and item.transport_class == "long_distance"
                and item.selected_mode.value in {"train", "high_speed_rail"}
                and item.departure_at == candidate.departure_at
                and item.from_endpoint.station_code == candidate.from_endpoint.station_code
                and item.to_endpoint.station_code == candidate.to_endpoint.station_code
                and (
                    item.route_id in {candidate.route_id, candidate.segments[0].service_number}
                    or any(
                        segment.service_number == candidate.segments[0].service_number
                        for segment in item.segments
                    )
                )
            ),
            None,
        )
        candidate_id = existing.candidate_id if existing is not None else candidate.candidate_id
        if existing is None and any(
            item["candidate_id"] == candidate_id for item in payload["candidates"]
        ):
            continue
        candidate_data = candidate.model_dump(mode="python")
        if existing is not None:
            old_facts = {
                fact["fact_assertion_id"] for fact in payload["fact_assertions"]
                if fact["entity_ref"]["entity_id"] == candidate_id
                and replaces_rail_field(fact["field_path"])
            }
            payload["fact_assertions"] = [
                fact for fact in payload["fact_assertions"]
                if fact["fact_assertion_id"] not in old_facts
            ]
            payload["field_provenance"] = [
                item for item in payload["field_provenance"]
                if item["entity_ref"]["entity_id"] != candidate_id
                or not replaces_rail_field(item["field_path"])
            ]
            _remove_fact_references(payload, old_facts)
            current = next(
                item for item in payload["candidates"] if item["candidate_id"] == candidate_id
            )
            for field in rail_fields | {"provider_evidence_scope_id", "observed_at"}:
                current[field] = candidate_data[field]
        else:
            candidate_data["active_constraint_ids"] = list(active_constraint_ids)
            payload["candidates"].append(candidate_data)
        for fact in rail.fact_assertions:
            if fact.entity_ref.entity_id == candidate.candidate_id:
                fact_data = fact.model_dump(mode="python")
                fact_data["entity_ref"]["entity_id"] = candidate_id
                payload["fact_assertions"].append(fact_data)
        for item in rail.field_provenance:
            if item.entity_ref.entity_id == candidate.candidate_id:
                provenance = item.model_dump(mode="python")
                provenance["entity_ref"]["entity_id"] = candidate_id
                payload["field_provenance"].append(provenance)
    source_ids = {source["source_record_id"] for source in payload["source_records"]}
    payload["source_records"].extend(
        source.model_dump(mode="python") for source in rail.source_records
        if source.source_record_id not in source_ids
    )
    return ResearchPacket.model_validate(payload)


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
    run_id = state.run_id

    output_key, assignment = resolve_agent_assignment(
        state.agent_assignments or {}, _NODE_NAME
    )
    task_desc = assignment["objective"]
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
            _NODE_NAME,
            trip_identity=state.controlled_trip_identity,
            required_route_scopes=required_route_scopes,
        ),
        task_desc=task_desc,
        upstream_packet_context=upstream_packet_context,
        active_constraint_ids=active_constraint_ids,
        state=state,
        recommended_tools=recommended_tools,
    )

    logger.info(
        "TransportResearcher 旅行理解=%s, 上游资料长度=%d",
        bool(state.current_requirements),
        len(upstream_packet_context),
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

    redo_requests_update: Optional[Dict[str, Any]] = None
    finalize_started_at: Optional[float] = None
    try:
        redo_requests_update = append_research_redo_messages(
            state=state,
            messages=messages,
            worker_base=_NODE_NAME,
            output_key=output_key,
        )
        await discover_domestic_rail_route(
            state=state,
            messages=messages,
            tool_context=tool_context,
            authoritative_tool_results=authoritative_tool_results,
            reference_services=reference_services,
            required_route_scopes=required_route_scopes,
        )
        # 只有确定性发现阶段产生的选中班次可以直接复用其筛选结果。
        initial_rail_results = list(authoritative_tool_results)
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
            required_route_scopes=required_route_scopes,
        )
        catalog = RecommendationCatalog(
            generation_id=generation_id,
            fact_data_revision=state.fact_data_revision,
            weather_data_revision=0,
        )
        for envelope in initial_rail_results:
            metadata = envelope.get("metadata") or {}
            leg = metadata.get("rail_route_leg") or {}
            if not metadata.get("rail_selected_train") or not leg:
                continue
            rail = compile_rail_followup_packet(
                state=state,
                catalog=catalog,
                envelope=envelope,
                task_id=output_key,
                existing_candidate_ids=set(),
                service_date=str(leg.get("service_date") or ""),
            )
            if rail is not None:
                packet = _merge_initial_rail_packet(
                    packet, rail, active_constraint_ids=active_constraint_ids
                )

        logger.info(
            "TransportResearcher 完成，key=%s candidates=%d facts=%d sources=%d finalize_ms=%.0f",
            output_key,
            len(packet.candidates),
            len(packet.fact_assertions),
            len(packet.source_records),
            (time.perf_counter() - finalize_started_at) * 1000.0,
        )

        outcomes = provider_evidence_outcomes(
            authoritative_tool_messages(authoritative_tool_results),
            expected_worker=_NODE_NAME,
            packet=packet,
            assignments=provider_assignments,
        )
        return {
            "messages": [
                AIMessage(content=f"已整理 {len(packet.candidates)} 个交通候选")
            ],
            "research_packets": {packet_state_key: packet},
            "agent_status": {output_key: "completed"},
            "tool_cache": tool_cache,
            "provider_reference_services": reference_services,
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
        if outcomes:
            result["provider_evidence_outcomes"] = outcomes

        if reference_services:
            result["provider_reference_services"] = reference_services
        return result
