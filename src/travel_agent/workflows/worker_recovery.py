"""Invocation recovery around typed workers, without replacing LangGraph."""
import contextvars
from copy import deepcopy
from functools import wraps
import hashlib
import json
import uuid

from .run_control import check_cancel_requested

current_worker_journal = contextvars.ContextVar("worker_journal", default=None)
current_execution_lease = contextvars.ContextVar("execution_lease", default=None)


class WorkerJournal:
    def __init__(self, store, run_id, scope_id, version, payload, lease_token):
        self.store, self.run_id, self.scope_id = store, run_id, scope_id
        self.version, self.payload, self.lease_token = version, payload, lease_token
        self.tool_cursor = 0

    async def commit(self):
        self.version = await self.store.save(
            self.run_id, self.scope_id, self.version, self.payload,
            lease_token=self.lease_token,
        )

    def next_tool(self, name, args):
        cursor = self.tool_cursor
        self.tool_cursor += 1
        identity = json.dumps([name, args], sort_keys=True, ensure_ascii=False)
        return f"{cursor}:{hashlib.sha256(identity.encode()).hexdigest()}"


def invocation_scope(state, node, config=None):
    # Exact semantic input, including amendments/history/generation. Timing and
    # cumulative metering change on resume and are not task identity.
    keys = {"run_id", "user_query", "controlled_trip_identity", "controlled_trip_identity_revision",
            "intent_spec", "intent_spec_revision", "planning_generation", "constraint_pack",
            "constraint_pack_revision", "fact_data_revision", "research_brief", "research_query_plan",
            "selected_mcp_servers", "session_anchor", "preset_context", "weather_context",
            "candidate_research_gaps", "recommendation_catalog", "research_packets", "messages"}
    fields = state.model_dump(mode="json", include=keys)
    from ..agents.utils import resolve_agent_assignment
    fields["assignment"] = resolve_agent_assignment(state.agent_assignments, node)
    # Pregel keeps this identity when resuming the same pending task, and
    # assigns a new one on the next dispatch even if semantic inputs match.
    # A cached failure must not stand in for a newly scheduled attempt.
    configurable = (config or {}).get("configurable", {})
    fields["graph_task_id"] = configurable.get("__pregel_task_id")
    digest = hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return f"{node}:v2:{digest}"


def with_worker_recovery(node, worker):
    @wraps(worker)
    async def wrapped(state, config):
        configurable = (config or {}).get("configurable", {})
        store = configurable.get("worker_journal_store")
        if store is None:
            try:
                from ..builders import get_components
                store = getattr(get_components(), "worker_journal_store", None)
            except RuntimeError:
                pass  # isolated offline workflows explicitly lack app stores
        if store is None or not state.run_id:
            return await worker(state, config)
        scope = invocation_scope(state, node, config)
        version, payload = await store.load(state.run_id, scope)
        journal = WorkerJournal(store, state.run_id, scope, version, payload,
                                current_execution_lease.get())
        check_cancel_requested(node)
        if "worker_result" in payload:
            await journal.commit()  # fence cached replay against lease takeover
            return deepcopy(payload["worker_result"])
        token = current_worker_journal.set(journal)
        try:
            result = await worker(state, config)
            # Commit typed result before returning it to Pregel. If Pregel dies
            # before checkpoint, replay this same update once into its reducer.
            # A HITL partial needs new input, and is never a completed packet.
            if not result.get("pending_user_choice"):
                for message in result.get("messages", []):
                    if getattr(message, "id", None) is None:
                        message.id = str(uuid.uuid4())
                journal.payload["worker_result"] = deepcopy(result)
                await journal.commit()
            return result
        finally:
            current_worker_journal.reset(token)
    return wrapped
