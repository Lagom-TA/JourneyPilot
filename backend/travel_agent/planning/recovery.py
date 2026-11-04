from __future__ import annotations

from copy import deepcopy
from functools import wraps
import hashlib
import json
import logging
import uuid
from ..runtime.cancellation import check_cancel_requested
from ..runtime.journal import (
    WorkerJournal,
    current_worker_journal,
    current_execution_lease,
)
from .assignments import resolve_agent_assignment
from .nodes import NODE_UNDERSTANDING_AGENT, RESEARCH_WORKER_NODES
from .research.execution_lease import observe_execution_lease


logger = logging.getLogger(__name__)


def invocation_scope(state, node, config=None):
    # 参与任务身份的全部语义输入，包含 amendment、历史与 generation；耗时与
    # 累计计量在恢复时会变化，不属于任务身份。理解阶段的问答随轮次推进，
    # 必须进入身份，否则同一节点的新一轮会错误命中上一轮的恢复日志。
    keys = {
        "run_id",
        "user_query",
        "controlled_trip_identity",
        "current_requirements",
        "research_plan",
        "planning_generation",
        "constraint_pack",
        "fact_data_revision",
        "session_anchor",
        "preset_context",
        "weather_context",
        "recommendation_catalog",
        "research_packets",
        "messages",
        "understanding_messages",
        "understanding_qa",
        "understanding_rounds",
        "understanding_pending_questions",
    }
    if node == "itinerary_planner":
        keys.update({
            "placement_skeleton", "trip_workspace", "composition_failure_context",
            "composition_reschedule_rounds", "research_redo_requests", "research_redo_rounds",
        })
    if node == NODE_UNDERSTANDING_AGENT:
        keys.update({
            "current_time", "plan_gate_amendment", "pending_intent_amendments",
            "refinement_context",
        })
    fields = state.model_dump(mode="json", include=keys)
    if node != NODE_UNDERSTANDING_AGENT:
        fields["assignment"] = resolve_agent_assignment(state.agent_assignments, node)
    fields["plan_gate_decision"] = state.plan_gate_decision
    # 恢复同一个待处理任务时 Pregel 保留该身份，而下次调度即使语义输入相同
    # 也会分配新值；缓存的失败结果不能代替新调度的尝试。
    configurable = (config or {}).get("configurable", {})
    fields["graph_task_id"] = configurable.get("__pregel_task_id")
    digest = hashlib.sha256(
        json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return f"{node}:{digest}"


def with_worker_recovery(node, worker):
    async def recover(state, config, *, allow_journal_replay=True):
        configurable = (config or {}).get("configurable", {})
        store = configurable.get("worker_journal_store")
        if store is None:
            try:
                from travel_agent.bootstrap.registry import get_components

                store = getattr(get_components(), "worker_journal_store", None)
            except RuntimeError:
                pass  # 隔离的离线工作流没有应用级 store
        if store is None or not state.run_id:
            return await worker(state, config)
        scope = invocation_scope(state, node, config)
        version, payload = await store.load(state.run_id, scope)
        journal = WorkerJournal(
            store, state.run_id, scope, version, payload, current_execution_lease.get()
        )
        check_cancel_requested(node)
        if allow_journal_replay and "worker_result" in payload:
            await journal.commit()  # 缓存重放前先提交，防止执行租约已被接管
            result = deepcopy(payload["worker_result"])
            if node == NODE_UNDERSTANDING_AGENT and "controlled_trip_identity" in result:
                run_store = configurable.get("trip_run_store")
                if run_store is not None:
                    await run_store.update_controlled_trip_identity(
                        state.run_id, controlled_trip_identity=result["controlled_trip_identity"]
                    )
            return result
        token = current_worker_journal.set(journal)
        try:
            result = await worker(state, config)
            # 先把强类型结果写入日志再返回 Pregel：若 Pregel 在 checkpoint 前
            # 退出，重放会把同一条更新再次送入 reducer。
            for message in result.get("messages", []):
                if getattr(message, "id", None) is None:
                    message.id = str(uuid.uuid4())
            journal.payload["worker_result"] = deepcopy(result)
            await journal.commit()
            return result
        finally:
            current_worker_journal.reset(token)

    @wraps(worker)
    async def wrapped(state, config):
        if node in RESEARCH_WORKER_NODES:
            draft = state.minimum_delivery_draft
            if (
                draft is None
                or not draft.planning_authorized
                or state.planning_generation is None
                or draft.planning_generation_id != state.planning_generation.generation_id
                or (state.plan_gate_decision or {}).get("action") != "approve"
                or state.run_budget is None
                or state.run_deadline is None
            ):
                raise PermissionError("研究任务需要已确认的当前方案")
            lease = await observe_execution_lease(state, config)
            if not lease.live:
                raise PermissionError(f"运行租约无效: {lease.reason_code}")
        return await recover(state, config)

    return wrapped
