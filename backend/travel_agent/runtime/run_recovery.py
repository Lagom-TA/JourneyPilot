"""失去执行器的 Run 的扫描与恢复判定。"""

from __future__ import annotations

from dataclasses import dataclass
from travel_agent.runtime.concurrency import PeriodicTask
from travel_agent.runtime.concurrency import run_forever
from travel_agent.runtime.run_commands import RUN_ENDED_BEFORE_CONSUMPTION
from travel_agent.runtime.run_commands import RUN_INTERRUPTED_BEFORE_CONSUMPTION
from travel_agent.runtime.run_commands import settle_run_terminal_commands
from travel_agent.runtime.run_contracts import RunRecoveryStatus
from travel_agent.runtime.run_contracts import TripRunMode
from travel_agent.runtime.run_contracts import TripRunResumePolicy
from travel_agent.runtime.run_contracts import TripRunStatus
from travel_agent.runtime.run_lifecycle import is_terminal_status
from travel_agent.storage.run_command_store import RunCommandStore
from travel_agent.storage.run_execution_store import RunExecutionStore
from travel_agent.storage.run_execution_store import RunRecoveryCandidate
from typing import Any
from typing import Awaitable
from typing import Callable
from typing import Dict
from typing import Optional
import asyncio
import logging


logger = logging.getLogger(__name__)


CheckpointProbe = Callable[[str], Awaitable[bool]]

#: 判定一个 run 是否留下了持久化交付产物（durable Bundle）。
BundleProbe = Callable[[str], Awaitable[bool]]


@dataclass(frozen=True)
class RunRecoveryOutcome:
    run_id: str
    previous_status: str
    resolved_status: str
    recovery_status: str
    reason: str


@dataclass(frozen=True)
class RunRecoveryReport:
    outcomes: tuple[RunRecoveryOutcome, ...] = ()
    failures: tuple[str, ...] = ()

    @property
    def resume_available_count(self) -> int:
        return sum(
            1
            for outcome in self.outcomes
            if outcome.recovery_status == RunRecoveryStatus.RESUME_AVAILABLE.value
        )

    @property
    def counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for outcome in self.outcomes:
            counts[outcome.recovery_status] = counts.get(outcome.recovery_status, 0) + 1
        return counts

    def log_summary(self, *, phase: str = "启动恢复") -> None:
        if not self.outcomes and not self.failures:
            logger.info("%s：没有孤儿 Run", phase)
            return
        if self.outcomes:
            logger.warning(
                "%s：%d 个 Run 失去执行器 | %s",
                phase,
                len(self.outcomes),
                "；".join(
                    f"{outcome.run_id} {outcome.previous_status}→{outcome.resolved_status}"
                    f"（{outcome.recovery_status}/{outcome.reason}）"
                    for outcome in self.outcomes
                ),
            )
        for failure in self.failures:
            logger.error("%s失败：%s", phase, failure)


class RunRecoveryService:
    """启动时扫描一次，之后按周期复扫。

    只在启动时扫描不够：租约可能在启动时仍未过期，那批 Run 会被第一次扫描跳过，
    之后没有扫描再处理它们。
    """

    def __init__(
        self,
        *,
        trip_run_store: Any,
        execution_store: RunExecutionStore,
        command_store: Optional[RunCommandStore] = None,
        checkpoint_probe: Optional[CheckpointProbe] = None,
        bundle_probe: Optional[BundleProbe] = None,
        sweep_seconds: int = 60,
    ) -> None:
        self._trip_run_store = trip_run_store
        self._execution_store = execution_store
        self._command_store = command_store
        self._checkpoint_probe = checkpoint_probe
        self._bundle_probe = bundle_probe
        self._sweep_seconds = max(5, sweep_seconds)
        self._poller = PeriodicTask("run_recovery", self._sweep_loop)
        self.last_report = RunRecoveryReport()

    async def sweep(self) -> RunRecoveryReport:
        candidates = await self._execution_store.list_recovery_candidates()
        outcomes: list[RunRecoveryOutcome] = []
        failures: list[str] = []
        for candidate in candidates:
            try:
                outcome = await self._recover(candidate)
            except Exception as exc:
                logger.error(
                    "恢复判定失败 run_id=%s error=%s",
                    candidate.run_id,
                    exc,
                    exc_info=True,
                )
                failures.append(f"{candidate.run_id}: {type(exc).__name__}: {exc}")
                continue
            if outcome is not None:
                outcomes.append(outcome)
        report = RunRecoveryReport(outcomes=tuple(outcomes), failures=tuple(failures))
        self.last_report = report
        return report

    def start(self) -> None:
        self._poller.start()

    async def stop(self) -> None:
        await self._poller.stop()

    async def _sweep_loop(self) -> None:
        await run_forever("孤儿扫描", self._step)

    async def _step(self) -> None:
        await asyncio.sleep(self._sweep_seconds)
        report = await self.sweep()
        if report.outcomes or report.failures:
            report.log_summary(phase="孤儿复扫")

    async def _recover(
        self, candidate: RunRecoveryCandidate
    ) -> Optional[RunRecoveryOutcome]:
        if candidate.status == TripRunStatus.CANCEL_REQUESTED:
            return await self._converge_cancelled(candidate)
        if candidate.status == TripRunStatus.RUNNING:
            return await self._converge_running(candidate)
        return await self._settle_inactive(candidate)

    async def _converge_cancelled(
        self, candidate: RunRecoveryCandidate
    ) -> RunRecoveryOutcome:
        """取消请求在重启恢复时完成。durable completion 优先，所以先看还能不能转。"""

        reason = "cancel_requested_completed_during_recovery"
        await self._execution_store.record_recovery(
            candidate.run_id,
            recovery_status=RunRecoveryStatus.RELEASED,
            recovery_reason=reason,
        )
        try:
            await self._trip_run_store.transition_status(
                candidate.run_id,
                TripRunStatus.CANCELLED,
                current_node=candidate.current_node,
                event_type="run.cancelled",
                payload={"reason": reason},
            )
        except ValueError:
            await self._settle_commands(
                candidate.run_id,
                run_status="unchanged",
                cancel_consumed=False,
                error_code=RUN_ENDED_BEFORE_CONSUMPTION,
                reason=reason,
            )
            return RunRecoveryOutcome(
                run_id=candidate.run_id,
                previous_status=candidate.status.value,
                resolved_status="unchanged",
                recovery_status=RunRecoveryStatus.RELEASED.value,
                reason="durable_status_moved_during_recovery",
            )

        await self._settle_commands(
            candidate.run_id,
            run_status=TripRunStatus.CANCELLED.value,
            cancel_consumed=True,
            error_code=RUN_ENDED_BEFORE_CONSUMPTION,
            reason=reason,
        )
        return RunRecoveryOutcome(
            run_id=candidate.run_id,
            previous_status=candidate.status.value,
            resolved_status=TripRunStatus.CANCELLED.value,
            recovery_status=RunRecoveryStatus.RELEASED.value,
            reason=reason,
        )

    async def _converge_running(
        self, candidate: RunRecoveryCandidate
    ) -> RunRecoveryOutcome:
        resumable, reason = await self._resume_verdict(candidate)
        recovery_status = (
            RunRecoveryStatus.RESUME_AVAILABLE
            if resumable
            else RunRecoveryStatus.NON_RESUMABLE
        )
        await self._execution_store.record_recovery(
            candidate.run_id,
            recovery_status=recovery_status,
            recovery_reason=reason,
        )
        try:
            await self._trip_run_store.transition_status(
                candidate.run_id,
                TripRunStatus.INTERRUPTED,
                current_node=candidate.current_node,
                event_type="run.interrupted",
                payload={"reason": reason, "recovery_status": recovery_status.value},
            )
        except ValueError:
            return RunRecoveryOutcome(
                run_id=candidate.run_id,
                previous_status=candidate.status.value,
                resolved_status="unchanged",
                recovery_status=recovery_status.value,
                reason="durable_status_moved_during_recovery",
            )

        await self._settle_commands(
            candidate.run_id,
            run_status=TripRunStatus.INTERRUPTED.value,
            cancel_consumed=False,
            error_code=RUN_INTERRUPTED_BEFORE_CONSUMPTION,
            reason=reason,
        )
        return RunRecoveryOutcome(
            run_id=candidate.run_id,
            previous_status=candidate.status.value,
            resolved_status=TripRunStatus.INTERRUPTED.value,
            recovery_status=recovery_status.value,
            reason=reason,
        )

    async def _settle_commands(
        self,
        run_id: str,
        *,
        run_status: str,
        cancel_consumed: bool,
        error_code: str,
        reason: str,
    ) -> None:
        """给这个 Run 留下的控制命令一个结论。

        没有执行器的 Run 上，pending 命令等不到消费者。不能留成永远 pending：
        回执接口会一直答「还在等」，实际上没有执行器会来消费。判据与仍存活的
        协调器共用同一份（`settle_run_terminal_commands`）。
        """

        if self._command_store is None:
            return
        await settle_run_terminal_commands(
            self._command_store,
            run_id,
            run_status=run_status,
            cancel_consumed=cancel_consumed,
            error_code=error_code,
            reason=reason,
        )

    async def _resume_verdict(
        self, candidate: RunRecoveryCandidate
    ) -> tuple[bool, str]:
        if candidate.resume_policy != TripRunResumePolicy.CHECKPOINT.value:
            return False, "run_has_no_checkpoint_resume_policy"
        if self._checkpoint_probe is None:
            return False, "checkpointer_unavailable"
        try:
            available = await self._checkpoint_probe(candidate.run_id)
        except Exception as exc:
            logger.warning(
                "checkpoint 合同校验拒绝恢复 run_id=%s error=%s", candidate.run_id, exc
            )
            return False, "checkpoint_contract_mismatch"
        if not available:
            return False, "process_restarted_without_checkpoint"
        return True, "process_restarted"

    async def _settle_inactive(
        self, candidate: RunRecoveryCandidate
    ) -> Optional[RunRecoveryOutcome]:
        """已经收口的 Run 只剩残留租约。矛盾的 durable 事实不猜，只标诊断。"""

        if (
            candidate.status == TripRunStatus.COMPLETED
            and candidate.mode == TripRunMode.DEEP.value
        ):
            has_bundle: Optional[bool] = None
            if self._bundle_probe is not None:
                try:
                    has_bundle = await self._bundle_probe(candidate.run_id)
                except Exception as exc:
                    logger.warning(
                        "交付产物存在性探测失败 run_id=%s error=%s",
                        candidate.run_id,
                        exc,
                    )
                    has_bundle = None
            if has_bundle is False:
                # 状态说完成、交付产物却不存在：完成事实不完整，不猜，只标诊断。
                reason = "completed_without_durable_bundle"
                await self._execution_store.record_recovery(
                    candidate.run_id,
                    recovery_status=RunRecoveryStatus.RECOVERY_CONTRACT_FAILURE,
                    recovery_reason=reason,
                )
                return RunRecoveryOutcome(
                    run_id=candidate.run_id,
                    previous_status=candidate.status.value,
                    resolved_status="unchanged",
                    recovery_status=RunRecoveryStatus.RECOVERY_CONTRACT_FAILURE.value,
                    reason=reason,
                )
        if is_terminal_status(candidate.status):
            await self._settle_commands(
                candidate.run_id,
                run_status=candidate.status.value,
                cancel_consumed=candidate.status == TripRunStatus.CANCELLED,
                error_code=RUN_ENDED_BEFORE_CONSUMPTION,
                reason="executor_gone_on_inactive_run",
            )

        released = await self._execution_store.release(
            candidate.run_id,
            recovery_status=RunRecoveryStatus.RELEASED,
            recovery_reason="executor_gone_on_inactive_run",
        )
        if not released:
            return None
        return RunRecoveryOutcome(
            run_id=candidate.run_id,
            previous_status=candidate.status.value,
            resolved_status="unchanged",
            recovery_status=RunRecoveryStatus.RELEASED.value,
            reason="executor_gone_on_inactive_run",
        )
