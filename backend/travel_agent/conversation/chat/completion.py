from __future__ import annotations
import logging
from typing import Any, AsyncGenerator, Dict
from travel_agent.runtime.run_contracts import TripRunStatus
from travel_agent.runtime.local_identity import LOCAL_USER_ID
from travel_agent.planning.delivery.public.bundle import (
    public_delivery_bundle,
    public_event_manifest,
)
from travel_agent.utils.json_helpers import strip_think_blocks
from travel_agent.runtime.cancellation import RunCancelled
from travel_agent.runtime.events import run_ts_ms

from travel_agent.conversation.stream_text import (
    strip_non_display_blocks,
    strip_thinking_text,
)
from travel_agent.memory.extraction_jobs import enqueue_memory_extraction

logger = logging.getLogger(__name__)


async def complete_chat(
    *,
    ctx,
    trip_run,
    trip_run_store,
    turns,
    accounting,
    delivery,
    lifecycle,
    stream_profile,
    background_job_worker,
    session_id,
    user_message,
    user_message_id,
    message_id,
) -> AsyncGenerator[Dict[str, Any], None]:
    current_run = await trip_run_store.get_run(trip_run.run_id)
    if current_run and current_run.status == TripRunStatus.CANCEL_REQUESTED:
        raise RunCancelled(
            trip_run.run_id,
            ctx.final_step_name or ctx.final_agent_name or "workflow",
        )
    if ctx.approval_gate:
        assistant_content = await turns.save_partial("waiting_input")
        cost_summary = await accounting.finalize_cost_summary(terminal=False)
        yield {
            "type": "chat_complete",
            "message_id": message_id,
            "run_id": trip_run.run_id,
            "run_status": TripRunStatus.AWAITING_INPUT.value,
            "final_content": assistant_content,
            "run_cost_summary": cost_summary,
            "ts_ms": run_ts_ms(),
        }
        lifecycle.stream_exit_reason = "stream_ended_at_awaiting_input"
        return

    assistant_content = strip_non_display_blocks(
        strip_thinking_text(strip_think_blocks(ctx.full_response))
    )
    assistant_type = "normal"
    deep_delivery_bundle = None
    if ctx.use_deep_research:
        deep_delivery_bundle = await delivery.bundle_store.get_current(trip_run.run_id)

    await turns.save_success(assistant_content, assistant_type)

    await enqueue_memory_extraction(
        user_id=LOCAL_USER_ID,
        session_id=session_id,
        user_message=user_message,
        user_message_id=user_message_id,
        assistant_message_id=message_id,
        profile_revision=stream_profile.revision if stream_profile else 0,
        portrait_baseline=stream_profile.auto_portrait if stream_profile else "",
        background_job_worker=background_job_worker,
    )

    current_bundle = None
    if ctx.use_deep_research:
        current_bundle = deep_delivery_bundle
        await delivery.require_completed_bundle(current_bundle, ctx.delivery_bundle_id)
        ctx.delivery_bundle_id = current_bundle.manifest.bundle_id
        ctx.delivery_manifest = public_event_manifest(
            current_bundle.manifest.model_dump(mode="json")
        )
    else:
        try:
            await trip_run_store.transition_status(
                trip_run.run_id,
                TripRunStatus.COMPLETED,
                current_node="workflow",
                event_type="run.completed",
                payload={"trace_event_count": len(ctx.trace_events)},
            )
        except ValueError:
            current_run = await trip_run_store.get_run(trip_run.run_id)
            if current_run and current_run.status in {
                TripRunStatus.CANCEL_REQUESTED,
                TripRunStatus.CANCELLED,
            }:
                raise RunCancelled(trip_run.run_id, "workflow")
            raise
    run_status = TripRunStatus.COMPLETED.value

    cost_summary = await accounting.finalize_cost_summary(terminal=True)

    if ctx.use_deep_research:
        ready_event, terminal_event = await delivery.completion_events(
            ctx.delivery_bundle_id
        )
        if current_bundle is None:
            raise RuntimeError("deep research delivery bundle was not loaded")

        delivery_ready_payload = {
            "type": "delivery_ready",
            "message_id": message_id,
            "run_id": trip_run.run_id,
            "event_seq": ready_event.sequence,
            "bundle_id": ctx.delivery_bundle_id,
            "manifest": ctx.delivery_manifest,
            "bundle": public_delivery_bundle(current_bundle),
            "ts_ms": run_ts_ms(),
        }
        delivery.delivery_ready_emitted = True
        yield delivery_ready_payload
        delivery.run_terminal_emitted = True
        yield {
            "type": "run_terminal",
            "message_id": message_id,
            "run_id": trip_run.run_id,
            "event_seq": terminal_event.sequence,
            "status": TripRunStatus.COMPLETED.value,
            "bundle_id": ctx.delivery_bundle_id,
            "run_cost_summary": cost_summary,
            "ts_ms": run_ts_ms(),
        }
        lifecycle.stream_exit_reason = "stream_ended_at_completed"
        return

    lifecycle.stream_exit_reason = f"stream_ended_at_{run_status}"
    yield {
        "type": "chat_complete",
        "message_id": message_id,
        "run_id": trip_run.run_id,
        "run_status": run_status,
        "final_content": assistant_content,
        "run_cost_summary": cost_summary,
        "ts_ms": run_ts_ms(),
    }
