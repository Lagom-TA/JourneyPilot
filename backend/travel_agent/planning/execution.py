from __future__ import annotations

import asyncio
import contextlib
import functools
import inspect
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Iterator, List, Optional, TypeVar
from langgraph.errors import GraphInterrupt
from travel_agent.planning.requirements.request_contracts import IntentAmendment, IntentAmendmentRejection
from .nodes import (
    NODE_INTENT_AMENDMENT_ROUTER as _INTENT_AMENDMENT_ROUTER,
    NODE_REQUEST_CONTRACT_NORMALIZER as _REQUEST_CONTRACT_NORMALIZER,
    RESEARCH_WORKER_NODES as _RESEARCH_WORKER_NODES,
)
from ..runtime.context import (
    ModelWindow,
    current_run_id,
    current_node,
    current_agent,
    current_run_deadline,
    current_run_budget,
    current_model_window,
)
from ..runtime.cancellation import (
    RunControlHandle,
    RunCancelled,
    check_cancel_requested,
    run_control_registry,
)
from ..runtime.events import run_ts_ms, emit_node_lifecycle, node_timing_registry
from ..runtime.budget import ensure_budget_baseline
from ..runtime.deadlines import DeadlineObservation, observe_run_deadline


logger = logging.getLogger(__name__)


def _state_run_id(state: Any) -> Optional[str]:
    if isinstance(state, dict):
        value = state.get("run_id")
    else:
        value = getattr(state, "run_id", None)
    return str(value) if value else None


NodeFn = TypeVar("NodeFn", bound=Callable[..., Any])


_COMPOSITION_WORKER_NODES = {"itinerary_planner"}


_DEADLINE_BLOCKED_WORKER_NODES = _RESEARCH_WORKER_NODES | _COMPOSITION_WORKER_NODES


_COMPOSITION_MODEL_WINDOW_NODES = _COMPOSITION_WORKER_NODES | {"budget_estimate"}


def is_structural_connector_round(state: Any, node_name: str) -> bool:
    """Whether this worker invocation only resolves a composed adjacency chain.

    Exact local connectors cannot be known before the itinerary skeleton exists.
    They are deterministic Provider lookups over already-selected endpoints, not a
    new candidate-discovery round, so they belong to the composition window even
    though the reusable implementation lives in ``transport_researcher``.
    """

    if node_name != "transport_researcher":
        return False
    assignments = getattr(state, "agent_assignments", None) or {}
    assignment = assignments.get(node_name) or {}
    connector_gaps = assignment.get("connector_gaps") or []
    required_classes = set(assignment.get("required_transport_classes") or [])
    return bool(
        getattr(state, "placement_skeleton", None) is not None
        and getattr(state, "trip_workspace_v2", None) is None
        and assignment.get("require_current_candidate") is True
        and connector_gaps
        and required_classes
        and required_classes <= {"public_transit", "flexible"}
    )


def _model_window_for_node(node_name: str, state: Any) -> ModelWindow:
    if node_name in _COMPOSITION_MODEL_WINDOW_NODES or is_structural_connector_round(
        state, node_name
    ):
        return "composition"
    return "research"


def _worker_window_closed(
    node_name: str,
    observation: DeadlineObservation,
    *,
    model_window: ModelWindow,
) -> bool:
    """Whether ``node_name`` has run out of the window its own calls belong to."""

    if model_window == "composition":
        return observation.composition_closed
    return observation.research_closed


def _blocked_research_worker_update(
    *,
    node_name: str,
    observed_deadline: Any,
    observation: DeadlineObservation,
) -> Dict[str, Any]:
    """Make a missed research/composition boundary converge through graph routes.

    The boundary is reported on the worker's own channels only. Routing is the
    Dispatcher's to write: it reads the terminal ``agent_status`` and the same
    deadline, and a parallel Send group turns any worker-side ``next_agent``
    write into two values for one step.
    """

    if observation.phase == "expired":
        return {
            "run_deadline": observed_deadline,
            "agent_status": {node_name: "failed"},
            "last_error": (
                "delivery deadline elapsed before research worker could start"
                if node_name in _RESEARCH_WORKER_NODES
                else "delivery deadline elapsed before itinerary composition"
            ),
        }
    return {
        "run_deadline": observed_deadline,
        "agent_status": {node_name: "partial"},
    }


@contextlib.contextmanager
def _run_control_scope(
    run_id: Optional[str], node_name: str, state: Any
) -> Iterator[ModelWindow]:
    """成对绑定与归还节点上下文，包括绑定中途失败及绕过 Pregel 的调用。"""
    with contextlib.ExitStack() as stack:
        stack.callback(current_run_id.reset, current_run_id.set(run_id))
        stack.callback(current_node.reset, current_node.set(node_name))
        stack.callback(current_agent.reset, current_agent.set(node_name))
        stack.callback(current_run_deadline.reset, current_run_deadline.set(None))
        # 预算快照是 Run 的属性、不随节点变化，所以在这里绑一次，节点里调到的每一层
        # 助手函数都免费继承它。
        stack.callback(
            current_run_budget.reset,
            current_run_budget.set(getattr(state, "run_budget", None)),
        )
        # The window a node's model calls draw on is a property of the node, so
        # it is bound here with the other run attribution rather than inside each
        # node body — helper functions the node calls inherit it for free.
        model_window = _model_window_for_node(node_name, state)
        stack.callback(
            current_model_window.reset, current_model_window.set(model_window)
        )
        yield model_window


def _ignored_after_delivery_update(state: Any, node_name: str) -> Dict[str, Any]:
    """The update that drops a worker's work once delivery owns the checkpoint.

    Both call sites (entry interception and post-return overwrite) build the
    same shape; the branches themselves differ in position and follow-up actions
    and are deliberately not merged.
    """

    return {
        "run_deadline": getattr(state, "run_deadline", None),
        "agent_status": {node_name: "ignored_after_delivery"},
    }


def _claim_fresh_amendments(
    claimed_supplements: List[Dict[str, str]],
    *,
    existing_ids: set[str],
) -> List[IntentAmendment]:
    """Fold this round's claimed commands into amendments worth injecting.

    Commands already carried in state (replayed deliveries) and empty-content
    entries are skipped: the former are already live, the latter carry nothing
    a prompt could act on.
    """

    return [
        IntentAmendment(
            command_id=str(item["command_id"]),
            category=str(item.get("category") or "other"),
            content=str(item.get("content") or "").strip(),
            source_kind="run_supplement",
        )
        for item in claimed_supplements
        if str(item.get("command_id") or "") not in existing_ids
        and str(item.get("content") or "").strip()
    ]


def _should_divert_to_amendment_router(
    *,
    fresh_amendments: List[IntentAmendment],
    state: Any,
    node_name: str,
) -> bool:
    """Whether a fresh supplement redirects this boundary to the router."""

    return bool(
        fresh_amendments
        and getattr(state, "request_contract", None) is not None
        and node_name not in {_REQUEST_CONTRACT_NORMALIZER, _INTENT_AMENDMENT_ROUTER}
    )


async def _settle_amendments(
    handle: Optional[RunControlHandle],
    *,
    node_name: str,
    run_id: str,
    claimed_applied_ids: List[str],
    intent_spec_revision: Any,
    generation_id: Any,
    rejected_amendments: List[IntentAmendmentRejection],
    deferred_command_ids: List[str],
) -> None:
    """Persist applied/rejected outcomes; deferred commands remain claimed for retry."""

    if handle is None:
        return
    if claimed_applied_ids:
        try:
            await handle.mark_supplements_applied(
                claimed_applied_ids,
                node=node_name,
                result={
                    "outcome": "applied",
                    "intent_spec_revision": intent_spec_revision,
                    "generation_id": generation_id,
                },
            )
        except Exception as settle_err:
            # 结算失败保留节点结果；claimed 命令由后续边界重试。
            logger.warning(
                "追加要求标记生效失败 run_id=%s node=%s error=%s",
                run_id,
                node_name,
                settle_err,
            )
    if rejected_amendments:
        for rejection in rejected_amendments:
            try:
                await handle.mark_supplements_rejected(
                    [rejection.command_id],
                    node=node_name,
                    result={
                        "outcome": (
                            "rejected_late"
                            if rejection.reason_code
                            in {
                                "research_window_closed",
                                "composition_window_closed",
                                "delivery_already_committed",
                            }
                            else "rejected"
                        ),
                        "impact": rejection.impact.value,
                        "reason_code": rejection.reason_code,
                        "requires_new_run": rejection.requires_new_run,
                    },
                )
            except Exception as settle_err:
                logger.warning(
                    "追加要求拒绝结论写入失败 run_id=%s node=%s error=%s",
                    run_id,
                    node_name,
                    settle_err,
                )
    if deferred_command_ids:
        # 未判定命令保留待重试；此处只记录日志，不写库或发事件。
        logger.info(
            "本轮 %d 条追加要求未产生判定，留待下一个节点边界 run_id=%s "
            "node=%s command_ids=%s",
            len(deferred_command_ids),
            run_id,
            node_name,
            deferred_command_ids,
        )


def with_run_control(node_name: str, fn: NodeFn) -> Callable[..., Awaitable[Any]]:
    """Wrap a LangGraph node with cancel checks and run attribution contextvars.

    ``functools.wraps`` keeps the wrapper transparent to LangGraph's signature
    inspection: ``inspect.signature`` follows ``__wrapped__``, so LangGraph still
    injects ``config`` (and ``writer``/``store`` when declared) into nodes that
    ask for them. Without this the wrapper's ``*args, **kwargs`` signature would
    hide those parameters and config-dependent nodes (workers, synthesizer,
    dispatcher) would never receive ``config``.
    """

    @functools.wraps(fn)
    async def _wrapped(state: Any, *args: Any, **kwargs: Any) -> Any:
        run_id = _state_run_id(state)
        with _run_control_scope(run_id, node_name, state) as model_window:
            started = time.perf_counter()
            ts_ms = run_ts_ms()
            try:
                check_cancel_requested(node_name)
                await ensure_budget_baseline()
                deadline = getattr(state, "run_deadline", None)
                observation: Optional[DeadlineObservation] = None
                if deadline is not None and hasattr(state, "model_copy"):
                    observed_deadline, observation = observe_run_deadline(deadline)
                    state = state.model_copy(update={"run_deadline": observed_deadline})
                    current_run_deadline.set(observed_deadline)
                    if (
                        node_name in _DEADLINE_BLOCKED_WORKER_NODES
                        and _worker_window_closed(
                            node_name,
                            observation,
                            model_window=model_window,
                        )
                    ):
                        # Do not enter a worker once the window its model calls draw
                        # on is closed — research and composition close separately.
                        return _blocked_research_worker_update(
                            node_name=node_name,
                            observed_deadline=observed_deadline,
                            observation=observation,
                        )
                handle = run_control_registry.get(run_id)
                if (
                    handle is not None
                    and handle.delivery_ready_event.is_set()
                    and node_name in _DEADLINE_BLOCKED_WORKER_NODES
                ):
                    # A detached/late worker must not overwrite a durable Bundle.
                    return _ignored_after_delivery_update(state, node_name)
                claimed_supplements = (
                    handle.pending_supplements() if handle is not None else []
                )
                existing_amendments = list(
                    getattr(state, "pending_intent_amendments", None) or []
                )
                existing_ids = {item.command_id for item in existing_amendments}
                fresh_amendments = _claim_fresh_amendments(
                    claimed_supplements, existing_ids=existing_ids
                )
                if fresh_amendments and hasattr(state, "model_copy"):
                    state = state.model_copy(
                        update={
                            "pending_intent_amendments": [
                                *existing_amendments,
                                *fresh_amendments,
                            ]
                        }
                    )
                await emit_node_lifecycle("started", node=node_name)
                divert_to_amendment_router = _should_divert_to_amendment_router(
                    fresh_amendments=fresh_amendments, state=state, node_name=node_name
                )
                if divert_to_amendment_router:
                    result = {
                        "intent_amendment_resume_node": node_name,
                    }
                else:
                    result = fn(state, *args, **kwargs)
                    if inspect.isawaitable(result):
                        result = await result
                applied_amendment_ids = set(
                    result.get("applied_intent_amendment_ids") or []
                    if isinstance(result, dict)
                    else []
                )
                rejected_amendments = [
                    IntentAmendmentRejection.model_validate(item)
                    for item in (
                        result.get("rejected_intent_amendments") or []
                        if isinstance(result, dict)
                        else []
                    )
                ]
                if (
                    handle is not None
                    and handle.delivery_ready_event.is_set()
                    and node_name in _DEADLINE_BLOCKED_WORKER_NODES
                ):
                    # The finalizer may win while an externally scheduled worker
                    # is returning. Drop that stale update rather than merging it
                    # into a checkpoint that already owns a Bundle identity.
                    result = _ignored_after_delivery_update(state, node_name)
                    applied_amendment_ids.clear()
                elif (
                    fresh_amendments
                    and isinstance(result, dict)
                    and node_name
                    not in {_REQUEST_CONTRACT_NORMALIZER, _INTENT_AMENDMENT_ROUTER}
                ):
                    result = dict(result)
                    result["pending_intent_amendments"] = [
                        *(result.get("pending_intent_amendments") or []),
                        *fresh_amendments,
                    ]
                if (
                    handle is not None
                    and node_name == "delivery_finalizer"
                    and isinstance(result, dict)
                    and result.get("delivery_persisted") is True
                ):
                    handle.mark_delivery_ready()
                # Keep a durable, non-decreasing checkpoint observation at every
                # successful graph boundary.  A node that explicitly replaces or
                # clears its deadline (approval/edit) owns that state transition.
                if (
                    deadline is not None
                    and isinstance(result, dict)
                    and "run_deadline" not in result
                ):
                    result = dict(result)
                    result["run_deadline"] = observe_run_deadline(
                        getattr(state, "run_deadline")
                    )[0]
                claimed_applied_ids = [
                    str(item.get("command_id"))
                    for item in claimed_supplements
                    if str(item.get("command_id") or "") in applied_amendment_ids
                ]
                # 每条读取命令恰好归入 applied、rejected 或 deferred。
                _read_command_ids = {
                    str(item.get("command_id") or "")
                    for item in claimed_supplements
                    if str(item.get("command_id") or "")
                }
                deferred_command_ids = sorted(
                    _read_command_ids
                    - set(claimed_applied_ids)
                    - {rejection.command_id for rejection in rejected_amendments}
                )
                # 结算读取已捕获的拒绝结论，不能从迟到写入覆盖后的 result 重算。
                _generation = (
                    result.get("planning_generation")
                    if isinstance(result, dict)
                    else None
                )
                await _settle_amendments(
                    handle,
                    node_name=node_name,
                    run_id=run_id,
                    claimed_applied_ids=claimed_applied_ids,
                    intent_spec_revision=(
                        result.get("intent_spec_revision")
                        if isinstance(result, dict)
                        else None
                    ),
                    generation_id=getattr(_generation, "generation_id", None),
                    rejected_amendments=rejected_amendments,
                    deferred_command_ids=deferred_command_ids,
                )
                await emit_node_lifecycle(
                    "completed",
                    node=node_name,
                    duration_ms=round((time.perf_counter() - started) * 1000.0, 3),
                )
                return result
            except (GraphInterrupt, RunCancelled, asyncio.CancelledError):
                raise
            except Exception as exc:
                await emit_node_lifecycle(
                    "failed",
                    node=node_name,
                    duration_ms=round((time.perf_counter() - started) * 1000.0, 3),
                    error_type=type(exc).__name__,
                )
                raise
            finally:
                node_timing_registry.record(
                    run_id,
                    node_name,
                    {
                        "duration_ms": round(
                            (time.perf_counter() - started) * 1000.0, 3
                        ),
                        "ts_ms": ts_ms,
                    },
                )

    return _wrapped
