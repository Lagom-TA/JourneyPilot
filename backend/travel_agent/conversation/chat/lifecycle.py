from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict, Optional
from travel_agent.runtime.run_contracts import TripRunStatus
from travel_agent.tools.exposure_ledger import get_tool_exposure_ledger
from travel_agent.runtime.budget import release_ledger
from travel_agent.runtime.cancellation import RunCancelled, run_control_registry
from travel_agent.runtime.events import node_timing_registry

logger = logging.getLogger(__name__)

_WORKFLOW_CANCEL_GRACE_SECONDS = 1.0


class ChatLifecycle:
    def __init__(
        self,
        *,
        run_id,
        trip_run_store,
        travel_workflow,
        use_deep_research,
        presentation,
        turns,
        lease,
        lease_keeper,
    ):
        self.run_id = run_id
        self.trip_run_store = trip_run_store
        self.travel_workflow = travel_workflow
        self.use_deep_research = use_deep_research
        self.presentation = presentation
        self.turns = turns
        self.lease = lease
        self.lease_keeper = lease_keeper
        self.workflow_task = None
        self.control_registered = False
        self.command_coordinator = None
        self.process_cleanup_done = False
        self.lease_released = False
        self.stream_exit_reason = "stream_closed_before_terminal"

    async def transition_to_awaiting_input(
        self,
        *,
        current_node: str,
        pending_user_choice: Dict[str, Any],
        event_type: str,
        payload: Dict[str, Any],
        terminal_reason_code: Optional[str] = None,
        terminal_gate_class: Optional[str] = None,
    ) -> None:
        try:
            await self.trip_run_store.transition_status(
                self.run_id,
                TripRunStatus.AWAITING_INPUT,
                current_node=current_node,
                pending_user_choice=pending_user_choice,
                event_type=event_type,
                payload=payload,
                terminal_reason_code=terminal_reason_code,
                terminal_gate_class=terminal_gate_class,
            )
        except ValueError:
            current_run = await self.trip_run_store.get_run(self.run_id)
            if current_run and current_run.status in {
                TripRunStatus.CANCEL_REQUESTED,
                TripRunStatus.CANCELLED,
            }:
                raise RunCancelled(self.run_id, current_node)
            raise

    async def converge_stream_exit(self, reason: str) -> None:
        """Ensure an abandoned response cannot leave an active TripRun behind."""
        for _ in range(3):
            current_run = await self.trip_run_store.get_run(self.run_id)
            if current_run is None:
                return
            if current_run.status == TripRunStatus.AWAITING_INPUT:
                try:
                    await self.turns.save_partial("waiting_input")
                except Exception as save_err:
                    logger.warning(f"等待态会话保存失败: {save_err}")
                return
            if current_run.status not in {
                TripRunStatus.RUNNING,
                TripRunStatus.CANCEL_REQUESTED,
            }:
                return
            current_node_name = (
                current_run.current_node
                or self.presentation.final_step_name
                or self.presentation.final_agent_name
                or "workflow"
            )
            target = (
                TripRunStatus.CANCELLED
                if current_run.status == TripRunStatus.CANCEL_REQUESTED
                else TripRunStatus.INTERRUPTED
            )
            try:
                await self.trip_run_store.transition_status(
                    self.run_id,
                    target,
                    current_node=current_node_name,
                    event_type=(
                        "run.cancelled"
                        if target == TripRunStatus.CANCELLED
                        else "run.interrupted"
                    ),
                    payload={
                        "reason": reason,
                        "current_node": current_node_name,
                    },
                )
                try:
                    await self.turns.save_partial("interrupted")
                except Exception as save_err:
                    logger.warning(f"断连会话保存失败: {save_err}")
                return
            except ValueError:
                continue
        current_run = await self.trip_run_store.get_run(self.run_id)
        if current_run and current_run.status in {
            TripRunStatus.RUNNING,
            TripRunStatus.CANCEL_REQUESTED,
        }:
            raise RuntimeError(f"TripRun stream exit did not converge: {self.run_id}")

    def log_cleanup_result(self, task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            logger.error("TripRun stream-exit cleanup task was cancelled")
        except Exception as cleanup_err:
            logger.error(
                f"TripRun stream-exit cleanup failed: {cleanup_err}", exc_info=True
            )

    def clear_process_run_state(self) -> None:
        if self.process_cleanup_done:
            return
        self.process_cleanup_done = True
        if self.control_registered:
            run_control_registry.unregister(self.run_id, self.lease.control_handle)

        get_tool_exposure_ledger().clear(self.run_id)

        node_timing_registry.clear(self.run_id)

        release_ledger(self.run_id)

    async def release_execution_lease(self, reason: str) -> None:
        if self.lease_released or self.lease_keeper is None:
            return
        self.lease_released = True
        try:
            await self.lease_keeper.release(reason=reason)
        except Exception as release_err:  # noqa: BLE001 — 交还失败只让租约自然过期
            logger.warning(
                "execution lease release failed run_id=%s error=%s",
                self.run_id,
                release_err,
            )

    def finish_detached_workflow(self, task: asyncio.Task) -> None:
        try:
            task.result()
            logger.info(
                "workflow_detached_after_cancel completed run_id=%s",
                self.run_id,
            )
        except asyncio.CancelledError:
            logger.info(
                "workflow_detached_after_cancel cancelled run_id=%s",
                self.run_id,
            )
        except Exception as workflow_err:
            logger.warning(
                "workflow_detached_after_cancel error run_id=%s error=%s",
                self.run_id,
                workflow_err,
            )
        finally:
            asyncio.ensure_future(self.release_execution_lease("workflow_detached"))
            self.clear_process_run_state()

    async def mark_safe_boundary(self) -> None:
        """把一个已经落盘的 checkpoint 记成安全边界。

        LLM 调用刚开始时不算 —— 那时还没有任何东西被持久化。
        """
        probe = getattr(self.travel_workflow, "probe_checkpoint", None)
        if probe is None or not self.use_deep_research:
            return
        try:
            _available, checkpoint_id = await probe(self.run_id)
        except Exception as probe_err:
            logger.warning(
                "安全边界探测失败 run_id=%s error=%s", self.run_id, probe_err
            )
            return
        if checkpoint_id:
            await self.lease_keeper.mark_safe_checkpoint(checkpoint_id)

    async def settle_run_commands(self) -> None:
        """给这个 Run 留下的控制命令一个结论。

        **不许留成永远 pending**：一条没人再消费的追加要求，回执接口会一直答「还在等」。
        结论按 durable 状态给，不按这次响应经历了什么。
        """

        if self.command_coordinator is None:
            return
        try:
            current_run = await self.trip_run_store.get_run(self.run_id)
            if current_run is None or current_run.status in {
                TripRunStatus.RUNNING,
                TripRunStatus.AWAITING_INPUT,
            }:
                return
            await self.command_coordinator.settle_terminal(current_run.status)
        except Exception as settle_err:
            logger.warning(
                "运行控制命令收口失败 run_id=%s error=%s",
                self.run_id,
                settle_err,
            )

    async def cleanup_stream_exit(self, reason: str) -> None:
        """Persist exit truth before bounded best-effort workflow shutdown."""
        if (
            self.workflow_task is not None
            and not self.workflow_task.done()
            and self.control_registered
        ):
            handle = run_control_registry.get(self.run_id)
            if handle is not None:
                handle.request_stop("stream_exit")

        try:
            await self.converge_stream_exit(reason)
        except Exception as convergence_err:
            logger.error(
                "TripRun durable stream-exit convergence failed run_id=%s error=%s",
                self.run_id,
                convergence_err,
                exc_info=True,
            )

        await self.settle_run_commands()
        if self.command_coordinator is not None:
            await self.command_coordinator.stop()

        if self.workflow_task is not None and not self.workflow_task.done():
            self.workflow_task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.shield(self.workflow_task),
                    timeout=_WORKFLOW_CANCEL_GRACE_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "workflow_detached_after_cancel run_id=%s grace_s=%s "
                    "reason=%s (detached task may still consume tools/LLM "
                    "until node boundary; durable TripRun already INTERRUPTED/CANCELLED)",
                    self.run_id,
                    _WORKFLOW_CANCEL_GRACE_SECONDS,
                    reason,
                )

                self.workflow_task.add_done_callback(self.finish_detached_workflow)
                return
            except asyncio.CancelledError:
                pass
            except Exception as workflow_err:
                logger.warning(
                    "Workflow shutdown failed run_id=%s error=%s",
                    self.run_id,
                    workflow_err,
                )

        await self.release_execution_lease(reason)
        self.clear_process_run_state()
