from __future__ import annotations
import logging
import uuid
from typing import Any, Dict, Optional
from travel_agent.config.loader import get_settings
from travel_agent.conversation.intake import (
    IntakeUnderstandingUnavailable,
    apply_intake_answers,
    controlled_identity_summary,
    intake_answers_complete,
    merge_intake_answers,
    understand_trip_intake,
    unavailable_intake,
    validate_intake_answers,
)
from travel_agent.conversation.intake_contracts import RouteName
from travel_agent.planning.requirements.identity_amendments import (
    classify_locked_identity_intent,
)
from travel_agent.runtime.run_contracts import (
    RunRecoveryStatus,
    TripRunResumePolicy,
    TripRunStatus,
)
from travel_agent.runtime.local_identity import LOCAL_USER_ID
from travel_agent.conversation.routing import RouteIntentUnavailable, classify_route
from travel_agent.runtime.run_lease import RunLeaseKeeper
from travel_agent.planning.nodes import CHECKPOINT_GATE_NODES
from travel_agent.runtime.events import run_ts_ms
from travel_agent.planning.workflow import CheckpointContractError

from travel_agent.conversation.chat.contracts import ChatRequest
from travel_agent.conversation.session_history import load_session_history
from travel_agent.conversation.input_safety import InputGuard
from .preset import load_preset_context
from dataclasses import dataclass
from typing import AsyncIterator
from travel_agent.conversation.intake_contracts import RouteDecision
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
) -> PreparedChat | ImmediateChat:
    user_msg = next(
        (
            m
            for m in reversed(request.messages)
            if m.role == "user" and m.content.strip()
        ),
        None,
    )
    if not user_msg:
        raise PreparationRefused(PreparationRejection.EMPTY_MESSAGE)

    user_message = user_msg.content.strip()
    user_message_id = user_msg.message_id or str(uuid.uuid4())
    session_id = request.session_id or str(uuid.uuid5(uuid.NAMESPACE_URL, f"{LOCAL_USER_ID}:session:{user_message_id}"))
    new_run_id = "trip_" + uuid.uuid5(uuid.NAMESPACE_URL, f"{LOCAL_USER_ID}:{session_id}:{user_message_id}").hex
    message_id = str(uuid.uuid4())
    if request.route_decision is not None:
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
    if request.run_id is None and request.controlled_trip_identity is not None:
        existing_run = await trip_run_store.get_run(new_run_id)
        if existing_run is not None and (
            existing_run.status != TripRunStatus.CREATED
            or await run_execution_store.has_live_lease(existing_run.run_id)
        ):
            async def _replayed_run_sse():
                yield {"type": "chat_start", "message_id": existing_run.assistant_message_id, "session_id": session_id, "run_id": existing_run.run_id, "route_decision": route_decision.model_dump(mode="json")}
                if existing_run.status == TripRunStatus.AWAITING_INPUT:
                    detail = await trip_run_store.get_detail(existing_run.run_id, event_limit=1)
                    choice = detail.state.pending_user_choice if detail else None
                    if isinstance(choice, dict) and choice.get("gate") == "plan":
                        yield {"type": "approval_gate_raised", "run_id": existing_run.run_id, "gate": "plan", "run_status": existing_run.status.value, "payload": choice.get("payload", {})}
                yield {"type": "chat_complete", "message_id": existing_run.assistant_message_id, "run_id": existing_run.run_id, "run_status": existing_run.status.value}
            return ImmediateChat(_replayed_run_sse())

    if use_deep_research:
        effective_gate = (
            request.plan_gate
            if request.plan_gate is not None
            else get_settings().run_control.plan_gate_enabled
        )
        if not effective_gate:
            raise PreparationRefused(PreparationRejection.PLAN_GATE_DISABLED)
        if request.run_id is None and checkpointer is None:
            raise PreparationRefused(
                PreparationRejection.GATE_REQUIRES_CHECKPOINT
            )

    if request.run_id is None and route_decision.route == RouteName.TRIP_PLANNING:
        try:
            saved_intake = await chat_session_memory.get_guided_intake(
                session_id=session_id, user_id=LOCAL_USER_ID,
            )
        except PermissionError as exc:
            from .errors import SessionAccessDenied
            raise SessionAccessDenied() from exc
        answers_submitted = request.guided_intake is not None
        if answers_submitted:
            if saved_intake is None:
                raise PreparationRefused(PreparationRejection.INTAKE_NOT_FOUND)
            try:
                guided = apply_intake_answers(saved_intake, request.guided_intake)
            except ValueError as exc:
                raise PreparationRefused(PreparationRejection.INTAKE_INVALID, explanation=str(exc)) from exc
        else:
            guided = saved_intake

        if request.controlled_trip_identity is not None:
            # 条件表单入口也必须先经过与自然语言入口相同的实质缺口评估。
            # 已答/已评估过的状态不会被重新出题；新身份才触发一次带身份的评估。
            identity = request.controlled_trip_identity
            # 之前的评估失败不能因为客户端补齐身份、附带 guided_intake 提交就被当作
            # 已评估。只有评估成功过，或已保存的待答问题仍在等待回答时才跳过重评估。
            needs_assessment = guided is None or (
                guided.understanding_status == "unavailable"
            ) or (
                not answers_submitted
                and guided.controlled_identity is None
                and intake_answers_complete(guided)
            )
            if needs_assessment:
                try:
                    guided = await understand_trip_intake(
                        guided.raw_input if guided is not None else user_message,
                        route_decision,
                        controlled_identity=identity,
                        previous=guided,
                    )
                except IntakeUnderstandingUnavailable as exc:
                    raise PreparationRefused(
                        PreparationRejection.INTAKE_UNAVAILABLE
                    ) from exc

            guided = guided.model_copy(
                update={
                    "controlled_identity": identity,
                    "missing_fields": [],
                }
            )
            if guided.questions and not intake_answers_complete(guided):
                try:
                    validate_intake_answers(guided, require_complete=False)
                except ValueError as exc:
                    raise PreparationRefused(
                        PreparationRejection.INTAKE_INVALID,
                        explanation=str(exc),
                    ) from exc
                await chat_session_memory.save_guided_intake(
                    session_id=session_id,
                    user_id=LOCAL_USER_ID,
                    title_seed=guided.raw_input,
                    guided_intake=guided,
                    user_message_id=user_message_id,
                    assistant_message_id=message_id,
                )

                async def _controlled_intake_sse():
                    yield {
                        "type": "guided_intake",
                        "message_id": message_id,
                        "session_id": session_id,
                        "guided_intake": guided.model_dump(mode="json"),
                    }
                    yield {"type": "chat_complete", "message_id": message_id}

                return ImmediateChat(_controlled_intake_sse())
            try:
                validate_intake_answers(guided)
            except ValueError as exc:
                raise PreparationRefused(
                    PreparationRejection.INTAKE_INVALID, explanation=str(exc)
                ) from exc
            user_message = merge_intake_answers(guided) + (
                "\n已确认旅行信息：" + controlled_identity_summary(identity)
            )
        else:
            if guided is None:
                try:
                    guided = await understand_trip_intake(user_message, route_decision)
                except IntakeUnderstandingUnavailable:
                    logger.warning("需求理解不可用，保留原文并显示待确认字段", exc_info=True)
                    guided = unavailable_intake(user_message, route_decision)
            elif request.guided_intake is None and user_message != guided.raw_input:
                guided = guided.model_copy(update={"additional_requirements": "\n".join(filter(None, [guided.additional_requirements, user_message]))[:1000]})
            if request.intake_destination is not None:
                from travel_agent.planning.requirements.identity_contracts import DESTINATION_PLACE_KINDS
                if request.intake_destination.kind not in DESTINATION_PLACE_KINDS:
                    raise PreparationRefused(PreparationRejection.INTAKE_INVALID, explanation="请选择可用于规划的城市或区域")
                guided = guided.model_copy(update={"seed_destinations": [request.intake_destination], "draft": guided.draft.model_copy(update={"destination_queries": [request.intake_destination.name], "destination_decided": True, "confirmed_destinations": [request.intake_destination]})})
            await chat_session_memory.save_guided_intake(
                session_id=session_id, user_id=LOCAL_USER_ID, title_seed=user_message,
                guided_intake=guided, user_message_id=user_message_id, assistant_message_id=message_id,
            )

            async def _guided_intake_sse():
                yield {"type": "guided_intake", "message_id": message_id, "session_id": session_id, "guided_intake": guided.model_dump(mode="json")}
                yield {"type": "chat_complete", "message_id": message_id}

            return ImmediateChat(_guided_intake_sse())

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

    if gate_resume and not request.run_id:
        raise PreparationRefused(PreparationRejection.GATE_REQUIRES_RUN)
    if request.run_id:
        detail = await trip_run_store.get_detail(request.run_id, event_limit=1)
        if detail is None:
            raise PreparationRefused(PreparationRejection.RUN_NOT_FOUND)
        authoritative_controlled_trip_identity = dict(
            detail.run.controlled_trip_identity or {}
        )
        identity_guard_text = (
            request.gate_decision.content
            if request.gate_decision is not None
            and request.gate_decision.action in {"edit", "supplement"}
            else ("" if request.gate_decision is not None else user_message)
        )
        if (
            classify_locked_identity_intent(identity_guard_text).classification
            == "change_requested"
        ):
            raise PreparationRefused(PreparationRejection.IDENTITY_LOCKED)
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
            if claimed is None:
                await lease_keeper.release(reason="resume_lost_status_race")
                raise PreparationRefused(PreparationRejection.RESUME_STATUS_RACE)
            trip_run = claimed
        elif gate_resume:
            raise PreparationRefused(PreparationRejection.GATE_STATUS_NOT_CONTINUABLE)
    else:
        authoritative_controlled_trip_identity = (
            request.controlled_trip_identity.model_dump(mode="json")
            if request.controlled_trip_identity
            else {}
        )
        trip_run = await trip_run_store.create_run(
            session_id=session_id,
            user_id=LOCAL_USER_ID,
            mode=mode,
            request_message_id=user_message_id,
            assistant_message_id=message_id,
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
            async def _existing_run_sse():
                yield {"type": "chat_start", "message_id": trip_run.assistant_message_id, "session_id": session_id, "run_id": trip_run.run_id, "route_decision": route_decision.model_dump(mode="json")}
                yield {"type": "chat_complete", "message_id": trip_run.assistant_message_id, "run_id": trip_run.run_id, "run_status": trip_run.status.value}
            return ImmediateChat(_existing_run_sse())
        message_id = trip_run.assistant_message_id
    if lease_keeper is None:
        lease_keeper = await lease.claim(trip_run.run_id)
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
    )


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
