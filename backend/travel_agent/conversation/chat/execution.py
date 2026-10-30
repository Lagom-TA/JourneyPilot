from __future__ import annotations
import asyncio
import logging
from typing import Any, AsyncGenerator, Dict
from travel_agent.config.loader import get_settings
from travel_agent.runtime.run_contracts import TripRunStatus
from travel_agent.runtime.local_identity import LOCAL_USER_ID
from travel_agent.runtime.run_commands import RunCommandCoordinator
from travel_agent.runtime.cancellation import RunCancelled, run_control_registry
from travel_agent.runtime.events import run_ts_ms, set_run_ts_anchor
from travel_agent.runtime.events import build_event_buffer

from travel_agent.conversation.chat.contracts import ChatRequest
from travel_agent.conversation.intake_lock import (
    IntakeChangedBeforeStart, intake_fingerprint, intake_session_lock,
)
from travel_agent.memory.extraction_jobs import load_user_profile
from .presentation import ChatPresentation, _trace_event_payload
from contextlib import aclosing
from .preparation import PreparedChat, _extract_interrupt_payload
from .turns import ChatTurns
from .accounting import ChatAccounting
from .delivery import ChatDelivery
from .lifecycle import ChatLifecycle
from .completion import complete_chat
from .failures import cancel_chat, fail_chat
from .text_events import _handle_token
from .tool_events import _handle_tool_start, _handle_tool_done
from .progress_events import (
    _handle_agent_activity,
    _handle_node_activity,
    _handle_context_compaction,
    _handle_context_report,
    _handle_state_update,
)

logger = logging.getLogger(__name__)


async def _clear_checkpointed_intake(
    *, run_id: str, session_id: str, expected_fingerprint: str,
    expected_user_message: str, expected_identity: Dict[str, Any],
    expected_evidence_sources: list[dict[str, Any]],
    workflow: Any, trip_run_store: Any, chat_session_memory: Any,
) -> bool:
    """仅在确认 checkpoint 已落盘后清除同一版 intake。"""
    probe = getattr(workflow, "probe_checkpoint_input", None)
    if probe is None:
        return False
    try:
        available, checkpoint_id = await probe(
            run_id, session_id=session_id, user_message=expected_user_message,
            controlled_trip_identity=expected_identity, intake_evidence_sources=expected_evidence_sources,
        )
    except Exception:
        logger.warning("无法确认 checkpoint；保留待恢复的旅行输入 run_id=%s", run_id, exc_info=True)
        return False
    if not available or not checkpoint_id:
        return False
    async with intake_session_lock(session_id):
        async with trip_run_store.transaction(run_id) as db_session:
            current = await chat_session_memory.get_guided_intake(
                session_id=session_id, user_id=LOCAL_USER_ID, db_session=db_session, for_update=True,
            )
            if intake_fingerprint(current) == expected_fingerprint:
                await chat_session_memory.clear_guided_intake(
                    session_id=session_id, user_id=LOCAL_USER_ID, db_session=db_session,
                )
    return True


_SSE_HANDLERS = {
    "token": _handle_token,
    "agent_activity": _handle_agent_activity,
    "tool_start": _handle_tool_start,
    "tool_done": _handle_tool_done,
    "context_compaction": _handle_context_compaction,
    "context_report": _handle_context_report,
    "state": _handle_state_update,
}


async def execute_chat(
    request: ChatRequest,
    prepared: PreparedChat,
    *,
    trip_run_store,
    chat_session_memory,
    user_profile_memory,
    travel_workflow,
    fast_workflow,
    run_command_store,
    delivery_bundle_store,
    background_job_worker,
    cost_ledger_store=None,
    usage_recorder=None,
) -> AsyncGenerator[Dict[str, Any] | None, None]:
    user_message = prepared.user_message
    user_message_id = prepared.user_message_id
    session_id = prepared.session_id
    message_id = prepared.message_id
    route_decision = prepared.route_decision
    use_deep_research = prepared.use_deep_research
    mode = prepared.mode
    request_trip_identity = prepared.request_trip_identity
    preset_context = prepared.preset_context
    preset_pack_constraints = prepared.preset_pack_constraints
    authoritative_controlled_trip_identity = (
        prepared.authoritative_controlled_trip_identity
    )
    checkpoint_resume = prepared.checkpoint_resume
    resume_payload = prepared.resume_payload
    trip_run = prepared.trip_run
    lease = prepared.lease
    lease_keeper = prepared.lease_keeper
    history = prepared.history
    session_anchor_data = prepared.session_anchor_data
    session_compressed = prepared.session_compressed

    event_queue = build_event_buffer(get_settings().streaming)
    heartbeat_seconds = get_settings().streaming.heartbeat_seconds

    _stream_profile = await load_user_profile(
        user_profile_memory,
        LOCAL_USER_ID,
    )

    workflow = travel_workflow if use_deep_research else fast_workflow

    set_run_ts_anchor()
    ctx = ChatPresentation(
        message_id=message_id,
        session_id=session_id,
        mode=mode,
        use_deep_research=use_deep_research,
        trace_run_id=trip_run.run_id,
    )
    turns = ChatTurns(
        chat_session_memory=chat_session_memory,
        presentation=ctx,
        run_id=trip_run.run_id,
        session_id=session_id,
        mode=mode,
        user_message=user_message,
        user_message_id=user_message_id,
        message_id=message_id,
        request_trip_identity=request_trip_identity,
    )
    accounting = ChatAccounting(
        run_id=trip_run.run_id,
        message_id=message_id,
        cost_ledger_store=cost_ledger_store,
        usage_recorder=usage_recorder,
        trip_run_store=trip_run_store,
    )
    delivery = ChatDelivery(
        run_id=trip_run.run_id,
        use_deep_research=use_deep_research,
        trip_run_store=trip_run_store,
        bundle_store=delivery_bundle_store,
    )
    lifecycle = ChatLifecycle(
        run_id=trip_run.run_id,
        trip_run_store=trip_run_store,
        travel_workflow=travel_workflow,
        use_deep_research=use_deep_research,
        presentation=ctx,
        turns=turns,
        lease=lease,
        lease_keeper=lease_keeper,
    )

    async def run_workflow() -> None:
        """在后台任务中运行工作流，将 state events 写入 event_queue。"""
        from travel_agent.runtime.journal import current_execution_lease

        lease_context = current_execution_lease.set(lease_keeper.lease_token)
        try:
            workflow_kwargs = {
                "user_message": user_message,
                "session_id": session_id,
                "user_id": LOCAL_USER_ID,
                "selected_mcp_servers": request.selected_mcp_servers,
                "conversation_history": history,
                "stream_queue": event_queue,
                "session_anchor": session_anchor_data,
                "session_compressed": session_compressed,
                "preset_context": preset_context,
                "preset_pack_constraints": preset_pack_constraints,
                "run_id": trip_run.run_id,
                "route_decision": route_decision.model_dump(mode="json"),
            }
            if use_deep_research:
                workflow_kwargs["resume_from_checkpoint"] = checkpoint_resume
                workflow_kwargs["resume_payload"] = resume_payload
                workflow_kwargs["plan_gate_enabled"] = request.plan_gate
                workflow_kwargs["controlled_trip_identity"] = (
                    authoritative_controlled_trip_identity
                )
                if not checkpoint_resume and prepared.intake_evidence_sources is not None:
                    workflow_kwargs["intake_evidence_sources"] = prepared.intake_evidence_sources
            async for state_event in workflow.astream(
                **workflow_kwargs,
            ):
                for node_name, state_update in state_event.items():
                    if node_name == "__interrupt__":
                        await event_queue.put(
                            ("gate", _extract_interrupt_payload(state_update))
                        )
                        continue
                    await event_queue.put(("state", node_name, state_update))
        except Exception as exc:
            await event_queue.put(("error", exc))
        finally:
            current_execution_lease.reset(lease_context)
            await event_queue.put(("done",))

    try:
        control_handle = run_control_registry.register(trip_run.run_id)
        lease.control_handle = control_handle
        lifecycle.control_registered = True
        lifecycle.command_coordinator = RunCommandCoordinator(
            run_command_store,
            trip_run_store,
            trip_run.run_id,
            control_handle,
            poll_seconds=get_settings().run_control.command_poll_seconds,
        )

        await lifecycle.command_coordinator.poll_once()
        lifecycle.command_coordinator.start()

        lease_keeper.start()

        async def start_run(db_session: Any = None) -> None:
            try:
                await trip_run_store.transition_status(
                    trip_run.run_id,
                    TripRunStatus.RUNNING,
                    event_type="run.started",
                    payload={"mode": mode, "checkpoint_thread_id": trip_run.run_id},
                    **({"db_session": db_session} if db_session is not None else {}),
                )
            except ValueError:
                current_run = await trip_run_store.get_run(trip_run.run_id)
                if current_run and current_run.status in {
                    TripRunStatus.CANCEL_REQUESTED,
                    TripRunStatus.CANCELLED,
                }:
                    raise RunCancelled(trip_run.run_id, "workflow")
                raise

        if not checkpoint_resume:
            if use_deep_research and prepared.intake_fingerprint:
                async with intake_session_lock(session_id):
                    async with trip_run_store.transaction(trip_run.run_id) as db_session:
                        current = await chat_session_memory.get_guided_intake(
                            session_id=session_id, user_id=LOCAL_USER_ID,
                            db_session=db_session, for_update=True,
                        )
                        if intake_fingerprint(current) != prepared.intake_fingerprint:
                            raise IntakeChangedBeforeStart("旅行信息已更新，请重新整理后继续。")
                        # Keep the exact saved input until a durable checkpoint
                        # exists; a crash after chat_start must not erase it.
                        await start_run(db_session)
            else:
                await start_run()
        yield {
            "type": "chat_start",
            "message_id": message_id,
            "run_id": trip_run.run_id,
            "session_id": session_id,
            "route_decision": route_decision.model_dump(mode="json"),
        }
        lifecycle.workflow_task = asyncio.create_task(run_workflow())

        intake_needs_checkpoint = bool(not checkpoint_resume and prepared.intake_fingerprint)
        while True:
            if event_queue.stalled:
                logger.warning(
                    "sse_consumer_stalled run_id=%s buffer=%s",
                    trip_run.run_id,
                    event_queue.snapshot(),
                )
                lifecycle.stream_exit_reason = "sse_consumer_stalled"
                return
            try:
                item = await event_queue.get(heartbeat_seconds)
            except asyncio.TimeoutError:
                yield None
                continue
            kind = item[0]

            if kind == "done":
                break
            if kind == "error":
                raise item[1]
            if kind == "node_lifecycle":
                _, payload = item
                await trip_run_store.record_node_lifecycle(
                    trip_run.run_id,
                    node=str(payload.get("node") or ""),
                    status=str(payload.get("status") or ""),
                    payload=payload,
                )
                async for progress_event in _handle_node_activity(payload, ctx):
                    yield progress_event
                continue
            if kind == "state_snapshot":
                _, state_snapshot = item
                await trip_run_store.record_state_snapshot(
                    trip_run.run_id,
                    state_snapshot=state_snapshot,
                )
                if intake_needs_checkpoint and prepared.intake_fingerprint:
                    intake_needs_checkpoint = not await _clear_checkpointed_intake(
                        run_id=trip_run.run_id, session_id=session_id,
                        expected_fingerprint=prepared.intake_fingerprint,
                        expected_user_message=user_message, expected_identity=authoritative_controlled_trip_identity,
                        expected_evidence_sources=prepared.intake_evidence_sources or [],
                        workflow=travel_workflow, trip_run_store=trip_run_store,
                        chat_session_memory=chat_session_memory,
                    )
                continue
            if kind == "gate":
                _, payload = item

                gate = str(payload.get("gate") or "approval")
                if gate != "plan":
                    raise RuntimeError(f"unsupported workflow gate: {gate}")
                gate_node = "plan_gate"
                ctx.approval_gate = payload
                await lifecycle.transition_to_awaiting_input(
                    current_node=gate_node,
                    pending_user_choice={
                        "type": "approval_gate",
                        "gate": gate,
                        "payload": payload,
                    },
                    event_type="run.gate_raised",
                    payload={
                        "gate": gate,
                        "payload": payload,
                    },
                )

                await lifecycle.mark_safe_boundary()
                if intake_needs_checkpoint and prepared.intake_fingerprint:
                    intake_needs_checkpoint = not await _clear_checkpointed_intake(
                        run_id=trip_run.run_id, session_id=session_id,
                        expected_fingerprint=prepared.intake_fingerprint,
                        expected_user_message=user_message, expected_identity=authoritative_controlled_trip_identity,
                        expected_evidence_sources=prepared.intake_evidence_sources or [],
                        workflow=travel_workflow, trip_run_store=trip_run_store,
                        chat_session_memory=chat_session_memory,
                    )
                yield {
                    "type": "approval_gate_raised",
                    "message_id": message_id,
                    "run_id": trip_run.run_id,
                    "gate": gate,
                    "payload": payload,
                    "run_status": TripRunStatus.AWAITING_INPUT.value,
                    "ts_ms": run_ts_ms(),
                }
                continue

            handler = _SSE_HANDLERS.get(kind)
            if handler is None:
                logger.warning(f"未知 SSE 事件 kind: {kind!r}")
                continue
            if kind == "state":
                _, node_name, state_update = item
                if node_name == "__final_state__":
                    await trip_run_store.record_state_snapshot(
                        trip_run.run_id,
                        state_snapshot=state_update,
                    )
                else:
                    await trip_run_store.record_node_update(
                        trip_run.run_id,
                        node=node_name,
                        trace_event_count=len(ctx.trace_events),
                    )
                if node_name == "plan_gate" and isinstance(state_update, dict):
                    decision = state_update.get("plan_gate_decision")
                    probe = getattr(travel_workflow, "probe_semantic_decision", None)
                    if isinstance(decision, dict) and decision.get("action") in {"semantic_confirmed", "semantic_correction"} and probe is not None:
                        try:
                            confirmed = await probe(
                                trip_run.run_id, action=decision["action"],
                                challenge_id=str(decision.get("challenge_id") or ""),
                                approval_token=str(decision.get("approval_token") or ""),
                            )
                        except Exception:
                            confirmed = False
                            logger.warning("无法验证语义确认 checkpoint run_id=%s", trip_run.run_id, exc_info=True)
                        if confirmed:
                            projected = dict(state_update)
                            projected["plan_gate_decision"] = {**decision, "checkpoint_confirmed": True}
                            item = (kind, node_name, projected)
            async for ev in handler(item, ctx):
                if ev.get("type") == "trace_event":
                    await trip_run_store.append_event(
                        trip_run.run_id,
                        "trace.event",
                        _trace_event_payload(ev),
                    )
                yield ev

            if kind in ("state", "tool_done", "tool_start"):
                for usage_ev in await accounting.flush_usage_updates():
                    yield usage_ev

        async with aclosing(
            complete_chat(
                ctx=ctx,
                trip_run=trip_run,
                trip_run_store=trip_run_store,
                turns=turns,
                accounting=accounting,
                delivery=delivery,
                lifecycle=lifecycle,
                stream_profile=_stream_profile,
                background_job_worker=background_job_worker,
                session_id=session_id,
                user_message=user_message,
                user_message_id=user_message_id,
                message_id=message_id,
            )
        ) as completion_events:
            async for event in completion_events:
                yield event
    except RunCancelled as cancelled:
        async with aclosing(
            cancel_chat(
                cancelled,
                ctx=ctx,
                trip_run=trip_run,
                trip_run_store=trip_run_store,
                turns=turns,
                accounting=accounting,
                lifecycle=lifecycle,
                message_id=message_id,
            )
        ) as cancel_events:
            async for event in cancel_events:
                yield event
    except asyncio.CancelledError:
        lifecycle.stream_exit_reason = "client_disconnected"
        raise
    except GeneratorExit:
        lifecycle.stream_exit_reason = "response_body_closed"
        raise
    except Exception as error:
        async with aclosing(
            fail_chat(
                error,
                ctx=ctx,
                trip_run=trip_run,
                trip_run_store=trip_run_store,
                turns=turns,
                accounting=accounting,
                delivery=delivery,
                lifecycle=lifecycle,
                message_id=message_id,
            )
        ) as failure_events:
            async for event in failure_events:
                yield event
    finally:
        cleanup_task = asyncio.create_task(
            lifecycle.cleanup_stream_exit(lifecycle.stream_exit_reason)
        )
        try:
            await asyncio.shield(cleanup_task)
        except asyncio.CancelledError:
            cleanup_task.add_done_callback(lifecycle.log_cleanup_result)
        except Exception as cleanup_err:
            logger.error(
                f"TripRun stream-exit cleanup failed: {cleanup_err}", exc_info=True
            )
