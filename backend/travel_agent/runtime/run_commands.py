"""运行控制命令的消费与终态收口。"""

from __future__ import annotations

from travel_agent.runtime.cancellation import RunControlHandle
from travel_agent.runtime.command_contracts import RunCommand
from travel_agent.runtime.command_contracts import RunCommandStatus
from travel_agent.runtime.command_contracts import RunCommandType
from travel_agent.runtime.concurrency import PeriodicTask
from travel_agent.runtime.concurrency import run_forever
from travel_agent.runtime.run_contracts import TripRunStatus
from travel_agent.storage.run_command_store import RunCommandStore
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
import asyncio
import logging


logger = logging.getLogger(__name__)


PAST_SUPPLEMENT_STAGE = "run_past_supplement_stage"


RUN_ENDED_BEFORE_CONSUMPTION = "run_ended_before_consumption"


RUN_INTERRUPTED_BEFORE_CONSUMPTION = "run_interrupted_before_consumption"


async def settle_run_terminal_commands(
    store: RunCommandStore,
    run_id: str,
    *,
    run_status: str,
    cancel_consumed: bool,
    error_code: str = RUN_ENDED_BEFORE_CONSUMPTION,
    reason: Optional[str] = None,
) -> None:
    """Run 不再有执行器时，给还没收口的命令一个结论。

    「没有命令永远停在 pending」是一条不变量，而它有两个到达点：仍在运行的协调器
    （`RunCommandCoordinator.settle_terminal`）和恢复扫描（`RunRecoveryService`）。
    两处必须使用同一判据，否则同一条命令会因进程当时是否仍在运行而得到两种结果。

    取消命令只在 Run 真的停下来时算 consumed：那是它要的效果。其他终态下留着的取消
    命令没有被执行（是运行自己结束的），和没能生效的追加要求一样明确拒绝。

    **顺序不可交换**：先 CONSUMED 掉取消，再统一 REJECTED，否则那条取消会被拒掉。
    """

    result: Dict[str, Any] = {"run_status": run_status}
    if reason is not None:
        result["reason"] = reason
    try:
        if cancel_consumed:
            await store.settle_open_for_run(
                run_id,
                status=RunCommandStatus.CONSUMED,
                command_types=[RunCommandType.CANCEL],
                result=result,
            )
        await store.settle_open_for_run(
            run_id,
            status=RunCommandStatus.REJECTED,
            error_code=error_code,
            result=result,
        )
    except Exception as exc:
        logger.warning(
            "运行控制命令收口失败 run_id=%s status=%s error=%s", run_id, run_status, exc
        )


class RunCommandCoordinator:
    """一个正在执行的 Run 的命令消费者。"""

    def __init__(
        self,
        store: RunCommandStore,
        trip_run_store,
        run_id: str,
        handle: RunControlHandle,
        *,
        poll_seconds: float,
    ) -> None:
        self._store = store
        self._trip_run_store = trip_run_store
        self._run_id = run_id
        self._handle = handle
        self._poll_seconds = max(0.2, poll_seconds)
        self._poller = PeriodicTask(f"run_commands:{run_id}", self._poll_loop)
        handle.supplement_applied_sink = self._on_supplements_applied
        handle.supplement_rejected_sink = self._on_supplements_rejected

    async def poll_once(self) -> List[RunCommand]:
        """取走这一轮的待处理命令并投递到 handle。返回被 claim 的命令。"""

        commands = await self._store.claim_pending(self._run_id)
        for command in commands:
            if command.command_type is RunCommandType.CANCEL:
                self._handle.request_stop("user_cancel")
                continue
            if self._handle.delivery_ready_event.is_set():
                await self._store.settle(
                    [command.command_id],
                    status=RunCommandStatus.REJECTED,
                    error_code=PAST_SUPPLEMENT_STAGE,
                    result={"run_id": self._run_id, "stage": "delivery_committed"},
                )
                continue
            self._handle.add_supplement(
                str(command.payload.get("category") or "other"),
                str(command.payload.get("content") or ""),
                command_id=command.command_id,
            )
        return commands

    def start(self) -> None:
        self._poller.start()

    async def stop(self) -> None:
        self._handle.supplement_applied_sink = None
        self._handle.supplement_rejected_sink = None
        await self._poller.stop()
        await self._release_unapplied_claims()

    async def _release_unapplied_claims(self) -> None:
        """手里还没落地的那几条放回 pending。

        Run 停在 AWAITING_INPUT 时终态收口按设计不运行，handle 连同它的
        supplements 一起被丢弃。不放回 pending 的话那条要求既不生效也不被拒绝，
        回执会一直停在 claimed。
        """

        pending = [
            str(item.get("command_id"))
            for item in self._handle.pending_supplements()
            if str(item.get("command_id") or "").strip()
        ]
        if not pending:
            return
        try:
            await self._store.release_claims(pending)
        except Exception as exc:
            logger.warning("未生效命令归还失败 run_id=%s error=%s", self._run_id, exc)

    async def settle_terminal(self, run_status: TripRunStatus | str) -> None:
        """Run 结束时给还没收口的命令一个结论。判据见 `settle_run_terminal_commands`。"""

        status = (
            run_status.value
            if isinstance(run_status, TripRunStatus)
            else str(run_status)
        )
        await settle_run_terminal_commands(
            self._store,
            self._run_id,
            run_status=status,
            cancel_consumed=status == TripRunStatus.CANCELLED.value,
        )

    async def _on_supplements_applied(
        self,
        command_ids: List[str],
        node: str,
        result: Dict[str, Any],
    ) -> None:
        await self._store.settle(
            command_ids,
            status=RunCommandStatus.CONSUMED,
            result={
                **result,
                "applied_at_node": node,
            },
        )
        for command_id in command_ids:
            try:
                await self._trip_run_store.append_event_once(
                    self._run_id,
                    "run.supplement_applied",
                    {"command_id": command_id, "node": node},
                    idempotency_key=f"{self._run_id}:supplement_applied:{command_id}",
                )
            except Exception as exc:
                logger.warning(
                    "追加要求生效事件写入失败 run_id=%s command_id=%s error=%s",
                    self._run_id,
                    command_id,
                    exc,
                )

    async def _on_supplements_rejected(
        self,
        command_ids: List[str],
        node: str,
        result: Dict[str, Any],
    ) -> None:
        reason_code = str(result.get("reason_code") or "supplement_rejected")
        await self._store.settle(
            command_ids,
            status=RunCommandStatus.REJECTED,
            error_code=reason_code,
            result={
                **result,
                "rejected_at_node": node,
            },
        )
        for command_id in command_ids:
            try:
                await self._trip_run_store.append_event_once(
                    self._run_id,
                    "run.supplement_rejected",
                    {
                        "command_id": command_id,
                        "node": node,
                        "reason_code": reason_code,
                        "requires_new_run": bool(result.get("requires_new_run")),
                    },
                    idempotency_key=f"{self._run_id}:supplement_rejected:{command_id}",
                )
            except Exception as exc:
                logger.warning(
                    "追加要求拒绝事件写入失败 run_id=%s command_id=%s error=%s",
                    self._run_id,
                    command_id,
                    exc,
                )

    async def _poll_loop(self) -> None:
        await run_forever(f"运行控制命令 run_id={self._run_id}", self._step)

    async def _step(self) -> None:
        try:
            await asyncio.wait_for(
                self._handle.wake_event.wait(), timeout=self._poll_seconds
            )
        except asyncio.TimeoutError:
            pass
        self._handle.wake_event.clear()
        await self.poll_once()
