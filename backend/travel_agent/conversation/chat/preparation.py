from __future__ import annotations
import hmac
import logging
import uuid
from typing import Any, Dict, Optional
from travel_agent.config.loader import get_settings
from travel_agent.runtime.run_contracts import (
    RunRecoveryStatus,
    TripRunResumePolicy,
    TripRunStatus,
)
from travel_agent.runtime.local_identity import LOCAL_USER_ID
from travel_agent.conversation.routing import RouteIntentUnavailable, classify_route
from travel_agent.runtime.context import run_attribution
from travel_agent.runtime.run_lease import RunLeaseKeeper
from travel_agent.planning.nodes import CHECKPOINT_GATE_NODES
from travel_agent.runtime.events import run_ts_ms
from travel_agent.planning.workflow import CheckpointContractError

from travel_agent.conversation.chat.contracts import ChatMessage, ChatRequest
from travel_agent.conversation.intake_contracts import RouteDecision, RouteName
from travel_agent.conversation.intake_lock import intake_session_lock
from travel_agent.conversation.session_history import load_session_history
from travel_agent.conversation.input_safety import InputGuard
from travel_agent.conversation.chat.refinement import (
    REFINEMENT_CLARIFICATION,
    answer_context,
    pending_clarification_context,
    understand_followup,
)
from travel_agent.conversation.routing import explicit_route_decision
from travel_agent.conversation.chat.errors import SessionAccessDenied, SessionHistoryUnavailable
from .preset import load_preset_context
from dataclasses import dataclass
from typing import AsyncIterator
from travel_agent.runtime.run_contracts import TripRun
from .errors import PreparationRefused, PreparationRejection
from .lease import RequestExecutionLease

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImmediateChat:
    events: AsyncIterator[Dict[str, Any]]


@dataclass(frozen=True)
class PreparedChat:
    user_message: str
    user_message_id: str
    session_id: str
    message_id: str
    route_decision: RouteDecision
    use_deep_research: bool
    mode: str
    request_trip_identity: Optional[Dict[str, Any]]
    preset_context: str
    preset_pack_constraints: Dict[str, str]
    authoritative_controlled_trip_identity: Dict[str, Any]
    checkpoint_resume: bool
    resume_payload: Optional[Dict[str, Any]]
    trip_run: TripRun
    lease: RequestExecutionLease
    lease_keeper: RunLeaseKeeper
    history: list
    session_anchor_data: Any
    session_compressed: bool
    refinement_action: Optional[str] = None
    refinement_bundle: Any = None
    refinement_context: str = ""
    refinement_instruction: str = ""


def _last_user_message(request: ChatRequest) -> Optional[ChatMessage]:
    """本轮最后一条非空用户消息。"""

    return next(
        (
            item
            for item in reversed(request.messages)
            if item.role == "user" and item.content.strip()
        ),
        None,
    )


async def _replay_run_events(
    *,
    run,
    trip_run_store,
    chat_session_memory,
    session_id: str,
    route_decision,
):
    """重放一个已存在 Run 的起始帧与等待中的门。"""

    yield {
        "type": "chat_start",
        "message_id": run.assistant_message_id,
        "session_id": session_id,
        "run_id": run.run_id,
        "route_decision": route_decision.model_dump(mode="json"),
    }
    if run.status == TripRunStatus.AWAITING_INPUT:
        detail = await trip_run_store.get_detail(run.run_id, event_limit=1)
        choice = detail.state.pending_user_choice if detail else None
        if isinstance(choice, dict) and choice.get("gate") == "plan":
            yield {
                "type": "approval_gate_raised",
                "run_id": run.run_id,
                "gate": "plan",
                "run_status": run.status.value,
                "payload": choice.get("payload", {}),
            }
        elif isinstance(choice, dict) and choice.get("gate") in {"understanding", "research"}:
            yield {
                "type": "understanding_questions",
                "run_id": run.run_id,
                "gate": choice["gate"],
                "run_status": run.status.value,
                "payload": choice.get("payload", {}),
            }
    final_content = None
    if run.status == TripRunStatus.COMPLETED and run.mode.value == "fast":
        try:
            final_content = await chat_session_memory.get_message_content(
                session_id=session_id, message_id=run.assistant_message_id,
            )
        except Exception as exc:
            logger.warning("读取已完成回答失败 run_id=%s error=%s", run.run_id, exc)
        if final_content is None:
            yield {
                "type": "error", "message_id": run.assistant_message_id,
                "run_id": run.run_id, "run_status": run.status.value,
                "message": "已完成的回答暂时无法读取，请刷新会话重试。",
            }
            return
    yield {
        "type": "chat_complete",
        "message_id": run.assistant_message_id,
        "run_id": run.run_id,
        "run_status": run.status.value,
        **({"final_content": final_content} if final_content is not None else {}),
    }


def _pending_gate_payload(detail: Any) -> Dict[str, Any]:
    """读取持久化 gate payload；没有等待中的门时返回空对象。"""

    state = getattr(detail, "state", None)
    choice = getattr(state, "pending_user_choice", None)
    if not isinstance(choice, dict) or choice.get("gate") not in {"plan", "understanding", "research"}:
        return {}
    payload = choice.get("payload")
    return dict(payload) if isinstance(payload, dict) else {}


def _validate_gate_decision_version(detail: Any, decision: Any) -> None:
    """非取消决定必须绑定当前持久化的 gate 版本。

    checkpoint 消费处还会重建当前 payload 再校验一次，覆盖版本变化的竞态。
    """

    if decision is None or decision.action == "cancel":
        return
    payload = _pending_gate_payload(detail)
    expected = str(payload.get("approval_token") or "").strip()
    supplied = str(decision.approval_token or "").strip()
    try:
        matches = bool(supplied) and hmac.compare_digest(
            supplied.encode("utf-8"), expected.encode("utf-8")
        )
    except UnicodeEncodeError:
        matches = False
    if matches:
        return
    revision = payload.get("revision")
    raise PreparationRefused(
        PreparationRejection.GATE_VERSION_STALE,
        current_revision=(
            revision
            if isinstance(revision, int) and not isinstance(revision, bool)
            else None
        ),
    )


def _resume_blocked_by_projection_failure(detail: Any) -> bool:
    """判断该 Run 是否因公开投影失败而终止，读取持久化的 last_error_code。

    finalizer 置为 FAILED 时把失败分类写入 ``last_error_code``；投影失败的 Run
    的 checkpoint 内容不会变化，继续运行只会得到相同结果，因此在进入恢复流程
    之前直接拒绝。
    """

    run = getattr(detail, "run", None)
    return (
        run is not None
        and getattr(run, "last_error_code", None) == "projection_failure"
    )


async def check_input_guard(user_message: str):
    """执行 InputGuard 检查，返回 guard result 对象。"""
    guard = InputGuard()
    return await guard.check(user_message)


async def prepare_chat(
    request: ChatRequest,
    *,
    trip_run_store,
    chat_session_memory,
    run_execution_store,
    travel_workflow,
    checkpointer,
    delivery_bundle_store=None,
) -> PreparedChat | ImmediateChat:
    user_msg = _last_user_message(request)
    session_id = request.session_id
    if not session_id and user_msg is not None and user_msg.message_id:
        session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{LOCAL_USER_ID}:session:{user_msg.message_id}"))
    if not session_id and user_msg is not None:
        session_id = str(uuid.uuid4())
        request = request.model_copy(update={"session_id": session_id})
    kwargs = {
        "trip_run_store": trip_run_store,
        "chat_session_memory": chat_session_memory,
        "run_execution_store": run_execution_store,
        "travel_workflow": travel_workflow,
        "checkpointer": checkpointer,
        "delivery_bundle_store": delivery_bundle_store,
    }
    if session_id and not request.gate_decision:
        async with intake_session_lock(session_id):
            return await _prepare_chat(request, **kwargs)
    return await _prepare_chat(request, **kwargs)


async def _understand_followup_attributed(
    run_id: str,
    text: str,
    identity: Any,
    bundle: Any,
):
    """已完成旅行的后续理解属于父 Run 的一次模型调用。

    完成态 Run 的用量摘要已在交付时结算；这一行只用于归因与成本记录，
    追加台账不回写已结算的摘要。
    """

    with run_attribution(run_id, node="chat_entry", agent="entry"):
        return await understand_followup(text, identity, bundle)


async def _prepare_chat(
    request: ChatRequest,
    *,
    trip_run_store,
    chat_session_memory,
    run_execution_store,
    travel_workflow,
    checkpointer,
    delivery_bundle_store=None,
) -> PreparedChat | ImmediateChat:
    user_msg = _last_user_message(request)
    if not user_msg:
        raise PreparationRefused(PreparationRejection.EMPTY_MESSAGE)
    if request.gate_decision is not None and not request.run_id:
        raise PreparationRefused(PreparationRejection.GATE_REQUIRES_RUN)

    user_message = user_msg.content.strip()
    user_message_id = user_msg.message_id or str(uuid.uuid4())
    session_id = request.session_id or str(uuid.uuid5(uuid.NAMESPACE_URL, f"{LOCAL_USER_ID}:session:{user_message_id}"))
    new_run_id = "trip_" + uuid.uuid5(uuid.NAMESPACE_URL, f"{LOCAL_USER_ID}:{session_id}:{user_message_id}").hex
    message_id = str(uuid.uuid4())
    parent_detail = None
    refinement_bundle = None
    refinement_action = None
    refinement_context = ""
    refinement_instruction = ""
    if request.run_id and request.gate_decision is None:
        parent_detail = await trip_run_store.get_detail(request.run_id, event_limit=1)
        if parent_detail is None:
            raise PreparationRefused(PreparationRejection.RUN_NOT_FOUND)
        if parent_detail.run.session_id != session_id:
            raise SessionAccessDenied()
        if parent_detail.run.status == TripRunStatus.COMPLETED:
            refinement_bundle = (
                await delivery_bundle_store.get_current(request.run_id)
                if delivery_bundle_store is not None else None
            )
            if refinement_bundle is None:
                raise PreparationRefused(PreparationRejection.CHECKPOINT_NOT_FOUND)
            try:
                refinement_instruction = await pending_clarification_context(
                    chat_session_memory, session_id, request.run_id, user_message
                )
            except PermissionError as exc:
                raise SessionAccessDenied() from exc
            except Exception as exc:
                logger.error("读取旅行追问失败 session=%s: %s", session_id, exc)
                raise SessionHistoryUnavailable() from exc
            try:
                decision = await _understand_followup_attributed(
                    request.run_id,
                    refinement_instruction or user_message,
                    parent_detail.run.controlled_trip_identity or {},
                    refinement_bundle,
                )
            except Exception as exc:
                logger.warning("当前旅行输入理解失败 run_id=%s error=%s", request.run_id, exc)
                raise PreparationRefused(PreparationRejection.ROUTE_UNAVAILABLE) from exc
            refinement_action = decision.action
            refinement_context = answer_context(
                parent_detail.run.controlled_trip_identity or {}, refinement_bundle
            )
            if decision.action == "clarify":
                reply = decision.response.strip() or "请再说明一下希望如何调整这趟旅行。"
                await chat_session_memory.save_turn(
                    session_id=session_id, user_id=LOCAL_USER_ID, mode="fast",
                    user_message=user_message, user_message_id=user_message_id,
                    assistant_message_id=message_id, assistant_content=reply,
                    assistant_display_content=reply, assistant_type="normal",
                    task_type=REFINEMENT_CLARIFICATION,
                    agent_name="", step_name="", thinking_steps=[], run_id=request.run_id,
                    controlled_trip_identity=None,
                )
                async def _clarification_sse():
                    yield {"type": "chat_start", "message_id": message_id, "session_id": session_id}
                    yield {"type": "chat_complete", "message_id": message_id, "final_content": reply, "requires_input": True}
                return ImmediateChat(_clarification_sse())
    if request.gate_decision is not None:
        route_decision = explicit_route_decision(RouteName.TRIP_PLANNING)
    elif refinement_action:
        route_decision = explicit_route_decision(
            RouteName.FAST_ANSWER if refinement_action == "answer" else RouteName.TRIP_REFINEMENT
        )
    elif request.route_decision is not None:
        route_decision = request.route_decision
    else:
        try:
            route_decision = await classify_route(
                user_message,
                explicit_route=request.route,
                has_trip_run=bool(request.run_id),
            )
        except RouteIntentUnavailable as exc:
            logger.warning(
                "Route intent unavailable | session=%s error=%s", session_id, exc
            )
            raise PreparationRefused(PreparationRejection.ROUTE_UNAVAILABLE)
    if route_decision.route == RouteName.TRIP_REFINEMENT and not request.run_id:
        raise PreparationRefused(PreparationRejection.REFINEMENT_REQUIRES_RUN)
    use_deep_research = route_decision.route in {
        RouteName.TRIP_PLANNING,
        RouteName.TRIP_REFINEMENT,
    }
    mode = "deep" if use_deep_research else "fast"

    request_trip_identity: Optional[Dict[str, Any]] = (
        request.controlled_trip_identity.model_dump(mode="json")
        if request.controlled_trip_identity
        else None
    )

    _guard_result = await check_input_guard(user_message)
    if _guard_result.is_blocked:
        logger.warning(
            f"InputGuard 拦截请求: {_guard_result.reason} | session={session_id}"
        )
        trip_run = await trip_run_store.create_run(
            session_id=session_id,
            user_id=LOCAL_USER_ID,
            mode=mode,
            request_message_id=user_message_id,
            assistant_message_id=message_id,
            resume_policy=TripRunResumePolicy.CLARIFY_ONLY,
        )
        await trip_run_store.transition_status(
            trip_run.run_id,
            TripRunStatus.FAILED,
            current_node="input_guard",
            error_code="safety_block",
            error_message="请求未通过安全检查",
            event_type="run.guard_blocked",
            payload={"reason": _guard_result.reason},
        )
        try:
            await chat_session_memory.save_turn(
                session_id=session_id,
                user_id=LOCAL_USER_ID,
                mode=mode,
                user_message=user_message,
                user_message_id=user_message_id,
                assistant_message_id=message_id,
                assistant_content=_guard_result.blocked_reply,
                assistant_display_content=_guard_result.blocked_reply,
                assistant_type="guard_blocked",
                task_type="input_guard",
                agent_name="InputGuard",
                step_name="安全检查",
                thinking_steps=[],
                run_id=trip_run.run_id,
                controlled_trip_identity=request_trip_identity,
            )
        except Exception as save_err:
            logger.warning(f"InputGuard 拦截消息保存失败: {save_err}")

        async def _blocked_sse():
            yield (
                {
                    "type": "chat_start",
                    "message_id": message_id,
                    "run_id": trip_run.run_id,
                    "session_id": session_id,
                }
            )
            yield (
                {
                    "type": "chat_chunk",
                    "message_id": message_id,
                    "content": _guard_result.blocked_reply,
                    "show_content": _guard_result.blocked_reply,
                }
            )
            yield (
                {
                    "type": "chat_complete",
                    "message_id": message_id,
                    "run_id": trip_run.run_id,
                    "guard_blocked": True,
                    "run_status": TripRunStatus.FAILED.value,
                    "ts_ms": run_ts_ms(),
                }
            )

        return ImmediateChat(_blocked_sse())

    if (
        route_decision.requires_confirmation
        and request.route_decision is None
        and request.route is None
    ):

        async def _route_confirmation_sse():
            yield (
                {
                    "type": "route_confirmation",
                    "message_id": message_id,
                    "session_id": session_id,
                    "route_decision": route_decision.model_dump(mode="json"),
                }
            )
            yield ({"type": "chat_complete", "message_id": message_id})

        return ImmediateChat(_route_confirmation_sse())

    existing_run = None
    if request.run_id is None or refinement_action:
        # 重复提交同一 message_id 时重放已存在的 Run，而不是再开一次规划；
        # 等待中的门（理解问题或方案确认）一并回放给前端。
        existing_run = await trip_run_store.get_run(new_run_id)
        if existing_run is not None and (
            existing_run.status != TripRunStatus.CREATED
            or await run_execution_store.has_live_lease(existing_run.run_id)
        ):
            return ImmediateChat(
                _replay_run_events(
                    run=existing_run,
                    trip_run_store=trip_run_store,
                    chat_session_memory=chat_session_memory,
                    session_id=session_id,
                    route_decision=route_decision,
                )
            )

    if use_deep_research:
        effective_gate = (
            request.plan_gate
            if request.plan_gate is not None
            else get_settings().run_control.plan_gate_enabled
        )
        if not effective_gate:
            raise PreparationRefused(PreparationRejection.PLAN_GATE_DISABLED)
        if (request.run_id is None or refinement_action) and checkpointer is None:
            raise PreparationRefused(
                PreparationRejection.GATE_REQUIRES_CHECKPOINT
            )

    preset_context, preset_pack_constraints = await load_preset_context(
        request.preset_id, LOCAL_USER_ID
    )
    authoritative_controlled_trip_identity: Dict[str, Any] = {}
    checkpoint_resume = False
    resume_payload: Optional[Dict[str, Any]] = None
    safe_checkpoint_id: Optional[str] = None
    lease = RequestExecutionLease(run_execution_store)
    lease_keeper = None
    gate_resume = request.gate_decision is not None

    if request.run_id and not refinement_action:
        detail = parent_detail or await trip_run_store.get_detail(request.run_id, event_limit=1)
        if detail is None:
            raise PreparationRefused(PreparationRejection.RUN_NOT_FOUND)
        if detail.run.session_id != session_id:
            raise SessionAccessDenied()
        authoritative_controlled_trip_identity = dict(
            detail.run.controlled_trip_identity or {}
        )
        if detail.run.status not in {
            TripRunStatus.CREATED,
            TripRunStatus.AWAITING_INPUT,
            TripRunStatus.FAILED,
            TripRunStatus.INTERRUPTED,
        }:
            raise PreparationRefused(
                PreparationRejection.RUN_STATUS_NOT_CONTINUABLE,
                current_status=detail.run.status.value,
            )
        trip_run = detail.run
        gate_node = (
            detail.run.current_node
            if detail.run.current_node in CHECKPOINT_GATE_NODES
            else None
        )
        if (
            use_deep_research
            and detail.run.status == TripRunStatus.AWAITING_INPUT
            and detail.run.resume_policy == TripRunResumePolicy.CHECKPOINT
            and gate_node
            and not gate_resume
        ):
            raise PreparationRefused(PreparationRejection.GATE_DECISION_REQUIRED)
        if gate_resume and not gate_node:
            raise PreparationRefused(PreparationRejection.GATE_NODE_REQUIRED)
        if gate_resume:
            _validate_gate_decision_version(detail, request.gate_decision)

        checkpoint_resume = (
            use_deep_research
            and detail.run.resume_policy == TripRunResumePolicy.CHECKPOINT
            and (
                detail.run.status in {TripRunStatus.FAILED, TripRunStatus.INTERRUPTED}
                or (detail.run.status == TripRunStatus.AWAITING_INPUT and gate_resume)
            )
        )
        if checkpoint_resume:
            if _resume_blocked_by_projection_failure(detail):
                raise PreparationRefused(PreparationRejection.PROJECTION_FAILURE)
            if checkpointer is None:
                raise PreparationRefused(
                    PreparationRejection.RESUME_REQUIRES_CHECKPOINT
                )

            recovery_execution = await run_execution_store.get(trip_run.run_id)
            if (
                recovery_execution is not None
                and recovery_execution.recovery_status
                in {
                    RunRecoveryStatus.NON_RESUMABLE,
                    RunRecoveryStatus.RECOVERY_CONTRACT_FAILURE,
                }
            ):
                raise PreparationRefused(PreparationRejection.RUN_NOT_RESUMABLE)
            probe_checkpoint = getattr(travel_workflow, "probe_checkpoint", None)
            try:
                checkpoint_available, safe_checkpoint_id = (
                    await probe_checkpoint(trip_run.run_id)
                    if probe_checkpoint is not None
                    else (False, None)
                )
            except CheckpointContractError as exc:
                raise PreparationRefused(
                    PreparationRejection.CHECKPOINT_CONTRACT_MISMATCH,
                    explanation=str(exc),
                ) from exc
            if not checkpoint_available:
                raise PreparationRefused(PreparationRejection.CHECKPOINT_NOT_FOUND)

            if request.gate_decision is not None:
                resume_payload = request.gate_decision.model_dump()
            if gate_resume:
                allowed_statuses = [TripRunStatus.AWAITING_INPUT]
                claim_node = gate_node or "plan_gate"
            else:
                allowed_statuses = [TripRunStatus.FAILED, TripRunStatus.INTERRUPTED]
                claim_node = None

            lease_keeper = await lease.claim(
                trip_run.run_id, checkpoint_id=safe_checkpoint_id
            )
            try:
                claimed = await trip_run_store.claim_checkpoint_resume(
                    trip_run.run_id,
                    allowed_statuses=allowed_statuses,
                    current_node=claim_node,
                    payload={
                        "checkpoint_thread_id": trip_run.run_id,
                        **(
                            {"gate": gate_node or "plan", "gate_decision": resume_payload}
                            if gate_resume
                            else {}
                        ),
                    },
                )
            except BaseException:
                # 准备阶段失败时立刻归还租约，避免留下仍算“活着”的幽灵执行器。
                await lease_keeper.release(reason="preparation_failed")
                raise
            if claimed is None:
                await lease_keeper.release(reason="resume_lost_status_race")
                raise PreparationRefused(PreparationRejection.RESUME_STATUS_RACE)
            trip_run = claimed
        elif gate_resume:
            raise PreparationRefused(PreparationRejection.GATE_STATUS_NOT_CONTINUABLE)
    else:
        authoritative_controlled_trip_identity = (
            dict(parent_detail.run.controlled_trip_identity or {})
            if refinement_action and parent_detail is not None
            else request.controlled_trip_identity.model_dump(mode="json")
            if request.controlled_trip_identity
            else {}
        )
        trip_run = await trip_run_store.create_run(
            session_id=session_id,
            user_id=LOCAL_USER_ID,
            mode=mode,
            request_message_id=user_message_id,
            assistant_message_id=message_id,
            parent_run_id=request.run_id if refinement_action else None,
            resume_policy=(
                TripRunResumePolicy.CHECKPOINT
                if use_deep_research and checkpointer is not None
                else TripRunResumePolicy.CLARIFY_ONLY
            ),
            controlled_trip_identity=authoritative_controlled_trip_identity or None,
            route_decision=route_decision.model_dump(mode="json"),
            run_id=new_run_id,
        )
        if trip_run.status != TripRunStatus.CREATED:
            return ImmediateChat(
                _replay_run_events(
                    run=trip_run,
                    trip_run_store=trip_run_store,
                    chat_session_memory=chat_session_memory,
                    session_id=session_id,
                    route_decision=route_decision,
                )
            )
        message_id = trip_run.assistant_message_id
    if lease_keeper is None:
        lease_keeper = await lease.claim(trip_run.run_id)
    try:
        if checkpoint_resume:
            history, session_anchor_data, session_compressed = [], None, False
        else:
            history, session_anchor_data, session_compressed = await load_session_history(
                chat_session_memory,
                LOCAL_USER_ID,
                session_id,
                mode,
                user_message,
                request_trip_identity,
                load_anchor=True,
            )

        return PreparedChat(
            user_message=user_message,
            user_message_id=user_message_id,
            session_id=session_id,
            message_id=message_id,
            route_decision=route_decision,
            use_deep_research=use_deep_research,
            mode=mode,
            request_trip_identity=request_trip_identity,
            preset_context=preset_context,
            preset_pack_constraints=preset_pack_constraints,
            authoritative_controlled_trip_identity=authoritative_controlled_trip_identity,
            checkpoint_resume=checkpoint_resume,
            resume_payload=resume_payload,
            trip_run=trip_run,
            lease=lease,
            lease_keeper=lease_keeper,
            history=history,
            session_anchor_data=session_anchor_data,
            session_compressed=session_compressed,
            refinement_action=refinement_action,
            refinement_bundle=refinement_bundle,
            refinement_context=refinement_context,
            refinement_instruction=refinement_instruction,
        )
    except BaseException:
        # 准备阶段失败时立刻归还租约，避免留下仍算“活着”的幽灵执行器。
        await lease_keeper.release(reason="preparation_failed")
        raise


def _extract_interrupt_payload(value: Any) -> Dict[str, Any]:
    """将 LangGraph v1 的 __interrupt__ 更新载荷归一化为 SSE 格式。"""
    interrupts = list(value or []) if isinstance(value, (list, tuple)) else [value]
    first = interrupts[0] if interrupts else None
    payload = getattr(first, "value", first)
    if not isinstance(payload, dict):
        payload = {"type": "interrupt", "payload": str(payload)}
    out = dict(payload)
    interrupt_id = getattr(first, "id", None)
    if interrupt_id:
        out["interrupt_id"] = interrupt_id
    return out
