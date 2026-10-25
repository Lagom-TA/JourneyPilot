from __future__ import annotations
import logging
import re
from typing import Any, AsyncGenerator, Dict, Optional
from travel_agent.planning.delivery.evidence_basis import (
    PublicProjectionContractViolation,
)
from travel_agent.runtime.run_contracts import TripRunStatus
from travel_agent.planning.delivery.public.bundle import (
    public_delivery_bundle,
    public_event_manifest,
)
from travel_agent.utils.json_helpers import strip_think_blocks
from travel_agent.planning.delivery.completion import DeliveryFinalizationError
from travel_agent.runtime.cancellation import RunCancelled, stop_verdict
from travel_agent.runtime.events import run_ts_ms

from travel_agent.conversation.stream_text import (
    strip_non_display_blocks,
    strip_thinking_text,
)
from .presentation import _trace_event_payload

logger = logging.getLogger(__name__)


def _format_llm_error(e: Exception) -> str:
    """
    将 LLM 提供商异常格式化为用户友好的中文消息。

    openai SDK 抛出的 APIStatusError 将错误体序列化为 str(e)：
      "Error code: 529 - {'type': 'error', 'error': {'type': 'overloaded_error', 'message': '...'}}"
    此函数从中提取内层 message 字段；若无法提取则回退到原始 str(e)。
    """
    raw = str(e)

    m = re.search(r"['\"]message['\"]\s*:\s*['\"]([^'\"]+)['\"]", raw)
    if m:
        inner_msg = m.group(1).strip()

        code_m = re.match(r"Error code:\s*(\d+)", raw)
        code = code_m.group(1) if code_m else ""
        prefix = f"[{code}] " if code else ""
        return f"{prefix}{inner_msg}"
    return raw


async def cancel_chat(
    cancelled: RunCancelled,
    *,
    ctx,
    trip_run,
    trip_run_store,
    turns,
    accounting,
    lifecycle,
    message_id,
) -> AsyncGenerator[Dict[str, Any], None]:
    try:
        assistant_content = await turns.save_partial("interrupted")
    except Exception as save_err:
        logger.warning(f"取消会话保存失败: {save_err}")
        assistant_content = strip_non_display_blocks(
            strip_thinking_text(strip_think_blocks(ctx.full_response))
        )
    stop_node = (
        cancelled.node_name or ctx.final_step_name or ctx.final_agent_name or "workflow"
    )

    verdict = stop_verdict(cancelled.reason)
    try:
        current_run = await trip_run_store.get_run(trip_run.run_id)
        if not verdict.user_decision:
            if current_run and current_run.status == TripRunStatus.RUNNING:
                await trip_run_store.transition_status(
                    trip_run.run_id,
                    TripRunStatus.INTERRUPTED,
                    current_node=stop_node,
                    error_code=verdict.error_code,
                    event_type="run.interrupted",
                    payload={"reason": verdict.payload_reason},
                )
        else:
            if current_run and current_run.status == TripRunStatus.RUNNING:
                await trip_run_store.transition_status(
                    trip_run.run_id,
                    TripRunStatus.CANCEL_REQUESTED,
                    current_node=stop_node,
                    event_type="run.control_requested",
                    payload={"action": "cancel", "source": "workflow_boundary"},
                )
            await trip_run_store.transition_status(
                trip_run.run_id,
                TripRunStatus.CANCELLED,
                current_node=stop_node,
                event_type="run.cancelled",
                payload={
                    "reason": verdict.payload_reason,
                    "trace_event_count": len(ctx.trace_events),
                },
            )
    except Exception as run_err:
        logger.warning(f"TripRun 停止状态保存失败: {run_err}")
    cost_summary = await accounting.finalize_cost_summary(terminal=True)
    if not verdict.user_decision:
        yield {
            "type": "error",
            "message": "这次规划被中断了（本机执行记录丢失），可以稍后继续。",
            "message_id": message_id,
            "run_id": trip_run.run_id,
            "run_status": verdict.terminal_status,
            "run_cost_summary": cost_summary,
        }
    else:
        yield {
            "type": "run_cancelled",
            "message_id": message_id,
            "run_id": trip_run.run_id,
            "final_content": assistant_content,
            "run_cost_summary": cost_summary,
            "ts_ms": run_ts_ms(),
        }
    lifecycle.stream_exit_reason = f"stream_ended_at_{verdict.terminal_status}"


async def fail_chat(
    e: Exception,
    *,
    ctx,
    trip_run,
    trip_run_store,
    turns,
    accounting,
    delivery,
    lifecycle,
    message_id,
) -> AsyncGenerator[Dict[str, Any], None]:

    terminal_failure: Exception = e
    recovered_delivery = None
    if ctx.use_deep_research:
        try:
            recovered_delivery = await delivery.load_durable_completed_delivery()
        except Exception as recovery_err:
            logger.error(
                f"已完成 Deep Run 的 durable delivery 恢复校验失败: {recovery_err}",
                exc_info=True,
            )
    if recovered_delivery is not None:
        current_bundle, ready_event, terminal_event = recovered_delivery
        try:
            recovered_manifest = public_event_manifest(
                current_bundle.manifest.model_dump(mode="json")
            )
            recovered_public_bundle = public_delivery_bundle(current_bundle)
        except PublicProjectionContractViolation as projection_err:
            logger.error(
                "durable Bundle 无法投影为公开交付面，放弃 durable 收口: "
                f"{projection_err}",
                exc_info=True,
            )
            terminal_failure = projection_err
        else:
            ctx.delivery_bundle_id = current_bundle.manifest.bundle_id
            ctx.delivery_manifest = recovered_manifest
            logger.warning(
                "Deep Run 已原子完成，但后提交 bookkeeping 失败；"
                "SSE 以 durable Bundle/terminal truth 收口: %s",
                e,
            )
            cost_summary = await accounting.finalize_cost_summary(terminal=True)
            if not delivery.delivery_ready_emitted:
                delivery.delivery_ready_emitted = True
                yield {
                    "type": "delivery_ready",
                    "message_id": message_id,
                    "run_id": trip_run.run_id,
                    "event_seq": ready_event.sequence,
                    "bundle_id": ctx.delivery_bundle_id,
                    "manifest": ctx.delivery_manifest,
                    "bundle": recovered_public_bundle,
                    "ts_ms": run_ts_ms(),
                }
            if not delivery.run_terminal_emitted:
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
            return
    logger.error(f"SSE 流式处理错误: {terminal_failure}", exc_info=terminal_failure)

    if isinstance(terminal_failure, DeliveryFinalizationError):
        terminal_reason_code = terminal_failure.record.failure_class.value
    elif isinstance(terminal_failure, PublicProjectionContractViolation):
        terminal_reason_code = "public_projection_contract_violation"
    else:
        terminal_reason_code = "unclassified_workflow_failure"

    sealed_status: Optional[TripRunStatus] = None
    try:
        durable_run = await trip_run_store.get_run(trip_run.run_id)
    except Exception as read_err:
        logger.error(
            f"失败收口无法读取 durable TripRun 状态: {read_err}", exc_info=True
        )
    else:
        if durable_run is not None and durable_run.status in {
            TripRunStatus.COMPLETED,
            TripRunStatus.CANCELLED,
        }:
            sealed_status = durable_run.status
    if sealed_status is None:
        try:
            await trip_run_store.transition_status(
                trip_run.run_id,
                TripRunStatus.FAILED,
                current_node="workflow",
                error_code=terminal_failure.__class__.__name__,
                error_message=_format_llm_error(terminal_failure),
                event_type="run.failed",
                payload={
                    "reason_code": terminal_reason_code,
                },
            )
        except ValueError:
            raced_run = await trip_run_store.get_run(trip_run.run_id)
            if raced_run is not None and raced_run.status in {
                TripRunStatus.COMPLETED,
                TripRunStatus.CANCELLED,
            }:
                sealed_status = raced_run.status
            else:
                logger.error(
                    "TripRun 失败状态写入被拒，且 durable 状态不是封存终态: %s",
                    raced_run.status.value if raced_run else "missing",
                )
        except Exception as run_err:
            logger.error(f"TripRun 失败状态保存失败: {run_err}", exc_info=True)
    failed_trace = ctx.next_trace(
        node="workflow",
        phase="postprocess",
        status="failed",
        output_summary=_format_llm_error(terminal_failure),
        risk_flags=["workflow_failed"],
    )
    try:
        await trip_run_store.append_event(
            trip_run.run_id,
            "trace.event",
            _trace_event_payload(failed_trace),
        )
    except Exception as run_err:
        logger.warning(f"TripRun 失败 trace 保存失败: {run_err}")
    try:
        terminal_cost_summary = await accounting.finalize_cost_summary(terminal=True)
    except Exception as cost_err:
        logger.warning(f"失败 run 成本汇总失败: {cost_err}")
        terminal_cost_summary = None
    yield failed_trace

    if sealed_status is TripRunStatus.COMPLETED:
        terminal_event = (
            recovered_delivery[2] if recovered_delivery is not None else None
        )
        yield {
            "type": "run_terminal",
            "message_id": message_id,
            "run_id": trip_run.run_id,
            "event_seq": terminal_event.sequence if terminal_event else None,
            "status": TripRunStatus.COMPLETED.value,
            "bundle_id": ctx.delivery_bundle_id,
            "run_cost_summary": terminal_cost_summary,
            "ts_ms": run_ts_ms(),
        }
    elif sealed_status is TripRunStatus.CANCELLED:
        yield {
            "type": "run_cancelled",
            "message_id": message_id,
            "run_id": trip_run.run_id,
            "final_content": strip_non_display_blocks(
                strip_thinking_text(strip_think_blocks(ctx.full_response))
            ),
            "run_cost_summary": terminal_cost_summary,
            "ts_ms": run_ts_ms(),
        }
    else:
        yield {
            "type": "run_failed",
            "message": "旅行方案暂时无法生成，请稍后重试。",
            "message_id": message_id,
            "run_id": trip_run.run_id,
            "run_cost_summary": terminal_cost_summary,
        }
    yield {
        "type": "error",
        "message": "旅行方案暂时无法生成，请稍后重试。",
        "message_id": message_id,
        "run_id": trip_run.run_id,
    }
