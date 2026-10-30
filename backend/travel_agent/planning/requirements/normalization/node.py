"""需求归一化节点。"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Optional

from langchain_core.runnables import RunnableConfig

from travel_agent.llm.router import get_model_router
from travel_agent.llm.task_routing import TaskKind, llm_for_task
from travel_agent.memory.context_builder import build_context_report
from travel_agent.planning.requirements.constraints.loading import (
    build_run_constraint_pack,
    load_constraint_sources,
)
from travel_agent.planning.requirements.constraints.presentation import (
    referenced_context_sections,
)
from travel_agent.planning.requirements.constraints.sources import (
    constraint_free_text_sources,
    structured_constraint_context,
)
from travel_agent.planning.requirements.normalization.clauses import (
    split_source_clauses,
)
from travel_agent.planning.requirements.normalization.model import (
    INTENT_NORMALIZATION_PROMPT_VERSION,
    normalize_clauses,
)
from travel_agent.planning.requirements.revision import (
    REQUEST_CONTRACT_POLICY_VERSION,
    build_request_contract_revision,
    constraint_pack_semantic_hash,
)
from travel_agent.planning.state import TravelAgentState

_NODE_NAME = "request_contract_normalizer"


def _source_kind(state: TravelAgentState, source: str, source_id: str) -> str:
    amendment = state.plan_gate_amendment
    if amendment is not None and source_id == amendment.command_id:
        return "plan_gate_amendment"
    if any(source_id == item.command_id for item in state.pending_intent_amendments):
        return "run_supplement"
    for item in state.unresolved_intent_amendments:
        if source_id == item.command_id:
            return item.source_kind
    return {
        "current_query": "current_request",
        "plan_gate_amendment": "plan_gate_amendment",
        "run_supplement": "run_supplement",
        "session_anchor": "trip_context",
        "memory_fact": "saved_preference",
    }.get(source, "trip_context")


def _intent_context_row(item: Any) -> Dict[str, Any]:
    return {
        "intent_id": item.intent_id,
        "kind": item.kind.value,
        "target": item.target.value,
        "strength": item.strength.value,
        "priority": item.priority,
        "value": item.value.model_dump(mode="json"),
        "public_summary": item.public_summary,
        "source_kind": item.source_kind,
        "impact_stages": list(item.impact_stages),
        "status": item.status,
    }


def _unresolved_context(state: TravelAgentState) -> List[Dict[str, Any]]:
    if state.intent_spec is None:
        return []
    rows: List[Dict[str, Any]] = []
    for item in state.intent_spec.unresolved_clauses:
        rows.append(
            {
                "source_ref_id": item.source_ref_id,
                "text": item.source_text[:500],
                "reason_code": item.reason_code,
            }
        )
    for item in state.intent_spec.conflicts:
        rows.append(
            {
                "conflict_id": item.conflict_id,
                "text": item.user_visible_summary[:500],
                "blocking": item.blocking,
            }
        )
    return rows[:20]


def _constraint_drafts_by_source(
    clauses: List[Any], normalized: Any
) -> Dict[str, List[Dict[str, Any]]]:
    source_by_clause = {item.clause_id: item.source_ref_id for item in clauses}
    result: Dict[str, List[Dict[str, Any]]] = {}
    for clause in normalized.clauses:
        source_ref_id = source_by_clause[clause.clause_id]
        for constraint in clause.constraints:
            result.setdefault(source_ref_id, []).append(
                {
                    "category": constraint.category,
                    "value": constraint.value,
                    "params": constraint.params.compact() or None,
                }
            )
    return result


async def request_contract_normalizer_node(
    state: TravelAgentState,
    config: Optional[RunnableConfig] = None,
) -> Dict[str, Any]:
    loaded = await load_constraint_sources(state)
    free_items = constraint_free_text_sources(state, loaded.memory_facts)
    sources = [
        (
            str(item["id"]),
            _source_kind(state, str(item.get("source") or ""), str(item["id"])),
            str(item.get("text") or ""),
        )
        for item in free_items
        if str(item.get("text") or "").strip()
    ]
    clauses = split_source_clauses(sources)
    recovered = {
        str(item["id"]): list(item["replayed_clauses"])
        for item in free_items if item.get("replayed_clauses")
    }
    if recovered:
        rebound = []
        for clause in clauses:
            rows = recovered.get(clause.source_ref_id)
            if rows is not None:
                if not rows or rows[0][1] != clause.source_text:
                    raise ValueError("cannot safely reconstruct unresolved amendment clauses")
                prior_id, _text = rows.pop(0)
                # The old checkpoint stored the exact clause, not its original offsets.
                clause = replace(clause, clause_id=prior_id, span_start=None, span_end=None)
            rebound.append(clause)
        if any(rows for rows in recovered.values()):
            raise ValueError("cannot safely reconstruct unresolved amendment clauses")
        clauses = rebound
    previous_contract = state.request_contract or state.request_contract_candidate
    previous_intents = (
        [
            _intent_context_row(item)
            for item in previous_contract.intent_spec.active_items
        ]
        if previous_contract is not None
        else []
    )
    normalized = await normalize_clauses(
        clauses=clauses,
        controlled_identity=state.controlled_trip_identity,
        llm=llm_for_task(get_model_router(), TaskKind.INTENT_NORMALIZE),
        previous_intents=previous_intents,
        existing_constraints=structured_constraint_context(
            state,
            user_profile=loaded.user_profile,
            manual_memory_facts=loaded.manual_memory_facts,
        ),
        unresolved_items=_unresolved_context(state),
    )
    constraint_pack = await build_run_constraint_pack(
        state,
        loaded=loaded,
        precomputed_free_text_constraints=_constraint_drafts_by_source(
            clauses, normalized
        ),
    )
    constraint_hash = constraint_pack_semantic_hash(constraint_pack)
    same_constraint_contract = bool(
        state.planning_generation is not None
        and state.planning_generation.constraint_hash == constraint_hash
    )
    constraint_revision = (
        state.constraint_pack_revision
        if same_constraint_contract
        else state.constraint_pack_revision + 1
    )
    amendment_ids = {
        item.command_id
        for item in [*state.pending_intent_amendments, *state.unresolved_intent_amendments]
    }
    if state.plan_gate_amendment is not None:
        amendment_ids.add(state.plan_gate_amendment.command_id)
    normalized_by_clause = {item.clause_id: item for item in normalized.clauses}
    amendment_clauses = [
        item for item in clauses if item.source_ref_id in amendment_ids
    ]
    research_contract_changed = any(
        normalized_by_clause[item.clause_id].constraints
        or any(
            stage in {"research"}
            for intent in normalized_by_clause[item.clause_id].intents
            for stage in intent.impact_stages
        )
        for item in amendment_clauses
    )
    preserve_generation_id = bool(
        previous_contract is not None
        and amendment_clauses
        and same_constraint_contract
        and not research_contract_changed
    )
    request_contract, generation = build_request_contract_revision(
        run_id=state.run_id,
        identity=state.controlled_trip_identity,
        identity_revision=state.controlled_trip_identity_revision,
        constraint_pack=constraint_pack,
        constraint_pack_revision=constraint_revision,
        clauses=clauses,
        normalized=normalized,
        previous=previous_contract,
        plan_revision=state.plan_gate_revision_count,
        preserve_generation_id=preserve_generation_id,
        research_plan=None,
        inherit_previous_research_plan=False,
    )

    stream_queue = (config or {}).get("configurable", {}).get("stream_queue")
    if stream_queue is not None:
        report = build_context_report(
            referenced_sections=referenced_context_sections(constraint_pack),
            compaction={"triggered": bool(state.session_compacted_this_turn)},
        )
        if report is not None:
            await stream_queue.put(("context_report", _NODE_NAME, report))

    unresolved_refs = {
        clause.source_ref_id
        for clause in clauses
        if normalized_by_clause[clause.clause_id].disposition.value in {"unresolved", "unsupported"}
    }
    considered_amendments = [
        *state.unresolved_intent_amendments,
        *state.pending_intent_amendments,
        *([state.plan_gate_amendment] if state.plan_gate_amendment is not None else []),
    ]
    unresolved_amendments = [
        item for item in considered_amendments if item.command_id in unresolved_refs
    ]
    # An unresolved command is not consumed merely because normalization ran.
    # Keep it until a later clarification actually resolves its source clauses.
    applied_amendment_ids = list(dict.fromkeys([
        *(item.command_id for item in considered_amendments if item.command_id not in unresolved_refs),
        *(str(item["id"]) for item in free_items if item.get("replayed_clauses") and str(item["id"]) not in unresolved_refs),
    ]))
    return {
        "request_contract": None,
        "request_contract_candidate": request_contract,
        "research_plan_error": None,
        "research_plan_retry_count": 0,
        "semantic_receipt": None,
        "semantic_candidate_hash": request_contract.content_hash,
        "research_brief": None,
        "research_query_plan": None,
        "capability_plan": None,
        "execution_plan": [],
        "agent_assignments": {},
        "intent_spec": request_contract.intent_spec,
        "intent_spec_revision": request_contract.intent_spec.revision,
        "constraint_pack": constraint_pack,
        "constraint_pack_revision": constraint_revision,
        "planning_generation": generation,
        "plan_gate_amendment": None,
        "pending_intent_amendments": [],
        "unresolved_intent_amendments": unresolved_amendments,
        "applied_intent_amendment_ids": applied_amendment_ids,
        "intent_amendment_route": None,
        "intent_amendment_resume_node": None,
        "prompt_versions": {
            "request_contract_normalization": INTENT_NORMALIZATION_PROMPT_VERSION,
        },
        "policy_versions": {
            "request_contract_revision": REQUEST_CONTRACT_POLICY_VERSION,
        },
    }
