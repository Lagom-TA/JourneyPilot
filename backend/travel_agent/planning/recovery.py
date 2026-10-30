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
from .research.authorization_context import (
    RESEARCH_WORKER_KINDS,
    build_research_worker_authorization,
    current_operation_authorization,
    observe_execution_lease,
    research_authorization_binding,
)


logger = logging.getLogger(__name__)


def invocation_scope(state, node, config=None):
    # 参与任务身份的全部语义输入，包含 amendment、历史与 generation；耗时与
    # 累计计量在恢复时会变化，不属于任务身份。
    keys = {
        "run_id",
        "user_query",
        "controlled_trip_identity",
        "controlled_trip_identity_revision",
        "intent_spec",
        "intent_spec_revision",
        "planning_generation",
        "constraint_pack",
        "constraint_pack_revision",
        "fact_data_revision",
        "research_brief",
        "research_query_plan",
        "selected_mcp_servers",
        "session_anchor",
        "preset_context",
        "weather_context",
        "recommendation_catalog",
        "research_packets",
        "messages",
    }
    fields = state.model_dump(mode="json", include=keys)
    fields["assignment"] = resolve_agent_assignment(state.agent_assignments, node)
    # 批准记录变化的 research worker 不能重放旧批准下写入的 worker 结果。
    fields["research_operation_approval"] = research_authorization_binding(state, node)
    # 恢复同一个待处理任务时 Pregel 保留该身份，而下次调度即使语义输入相同
    # 也会分配新值；缓存的失败结果不能代替新调度的尝试。
    configurable = (config or {}).get("configurable", {})
    fields["graph_task_id"] = configurable.get("__pregel_task_id")
    digest = hashlib.sha256(
        json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return f"{node}:v2:{digest}"


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
            return deepcopy(payload["worker_result"])
        token = current_worker_journal.set(journal)
        try:
            result = await worker(state, config)
            # 先把强类型结果写入日志再返回 Pregel：若 Pregel 在 checkpoint 前
            # 退出，重放会把同一条更新再次送入 reducer。HITL 部分结果需要新的
            # 用户输入，不视为完整 packet。
            if not result.get("pending_user_choice"):
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
        if node not in RESEARCH_WORKER_KINDS:
            return await recover(state, config)
        lease = await observe_execution_lease(state, config)
        authorization = build_research_worker_authorization(
            state, worker_kind=node, lease=lease
        )
        if not authorization.authorized:
            logger.warning(
                "research worker authorization denied node=%s run_id=%s reason=%s",
                node,
                getattr(state, "run_id", None),
                authorization.unauthorized_reason,
            )
            raise PermissionError("research worker is not authorized")
        token = current_operation_authorization.set(authorization)
        try:
            return await recover(
                state, config, allow_journal_replay=authorization.authorized
            )
        finally:
            current_operation_authorization.reset(token)

    return wrapped
