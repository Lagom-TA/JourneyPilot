"""Run 执行租约的持有、续租与释放。"""

from __future__ import annotations

from travel_agent.runtime.run_contracts import RunRecoveryStatus
from travel_agent.storage.run_execution_store import RunExecutionStore
from typing import Awaitable
from typing import Callable
from typing import Optional
import asyncio
import logging


logger = logging.getLogger(__name__)


LeaseLostCallback = Callable[[str], Awaitable[None] | None]


class RunLeaseKeeper:
    """一个 Run 的租约。claim 成功后才允许开始执行。"""

    def __init__(
        self,
        store: RunExecutionStore,
        run_id: str,
        *,
        lease_seconds: int,
        heartbeat_seconds: int,
        failure_threshold: int,
        on_lease_lost: Optional[LeaseLostCallback] = None,
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._failure_threshold = failure_threshold
        self._on_lease_lost = on_lease_lost
        self._lease_token: Optional[str] = None
        self._task: Optional[asyncio.Task] = None
        self._lost = False

    @property
    def lease_token(self) -> Optional[str]:
        return self._lease_token

    async def claim(self, *, last_safe_checkpoint_id: Optional[str] = None) -> bool:
        execution = await self._store.claim(
            self._run_id,
            lease_seconds=self._lease_seconds,
            last_safe_checkpoint_id=last_safe_checkpoint_id,
        )
        if execution is None or not execution.lease_token:
            return False
        self._lease_token = execution.lease_token
        self._lost = False
        return True

    def start(self) -> None:
        """开始心跳。claim 之前调用是编程错误。"""

        if self._lease_token is None:
            raise RuntimeError(f"lease not claimed for run {self._run_id}")
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._heartbeat_loop())
        _active_keepers[self._run_id] = self

    async def mark_safe_checkpoint(self, checkpoint_id: str) -> None:
        if not checkpoint_id or self._lease_token is None or self._lost:
            return
        try:
            await self._store.mark_safe_checkpoint(
                self._run_id,
                lease_token=self._lease_token,
                checkpoint_id=checkpoint_id,
            )
        except Exception as exc:
            logger.warning(
                "安全 checkpoint 记录失败 run_id=%s error=%s", self._run_id, exc
            )

    async def release(
        self,
        *,
        recovery_status: RunRecoveryStatus = RunRecoveryStatus.RELEASED,
        reason: Optional[str] = None,
    ) -> None:
        _drop_active_keeper(self)
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        token = self._lease_token
        self._lease_token = None
        if token is None:
            return
        try:
            await self._store.release(
                self._run_id,
                lease_token=token,
                recovery_status=recovery_status,
                recovery_reason=reason,
            )
        except Exception as exc:
            logger.warning("执行租约释放失败 run_id=%s error=%s", self._run_id, exc)

    async def _heartbeat_loop(self) -> None:
        failures = 0
        while True:
            await asyncio.sleep(self._heartbeat_seconds)
            token = self._lease_token
            if token is None:
                return
            try:
                renewed = await self._store.heartbeat(
                    self._run_id,
                    lease_token=token,
                    lease_seconds=self._lease_seconds,
                    recovery_status=RunRecoveryStatus.RUNNING,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failures += 1
                logger.warning(
                    "执行租约心跳失败 run_id=%s 连续第 %d 次 error=%s",
                    self._run_id,
                    failures,
                    exc,
                )
                if failures < self._failure_threshold:
                    continue
                await self._lose_lease("heartbeat_write_failed")
                return
            if not renewed:
                await self._lose_lease("lease_taken_over")
                return
            failures = 0

    async def _lose_lease(self, reason: str) -> None:
        self._lost = True
        logger.error(
            "执行租约失效 run_id=%s reason=%s，停止发起新的外部调用",
            self._run_id,
            reason,
        )
        _drop_active_keeper(self)
        if self._on_lease_lost is None:
            return
        try:
            result = self._on_lease_lost(reason)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            logger.error("租约失效回调失败 run_id=%s error=%s", self._run_id, exc)


_active_keepers: dict[str, RunLeaseKeeper] = {}


def _drop_active_keeper(keeper: "RunLeaseKeeper") -> None:
    """只在这一格仍是自己的 keeper 时移除。

    按 run_id 盲删会移除接管者的 keeper；关闭时 `release_all_leases` 就看不到它，
    它的租约保留一个未来的过期时间，下一个进程需要等到租约过期。
    """

    if _active_keepers.get(keeper._run_id) is keeper:
        _active_keepers.pop(keeper._run_id, None)


async def release_all_leases(*, reason: str = "process_shutdown") -> int:
    """进程关闭时交还所有租约。

    状态收敛不在这里做：SSE 协程各自的退出路径负责那件事。这里只保证下一次启动
    的恢复扫描立刻能看见「没有执行器」，而不是等到租约过期。
    """

    keepers = list(_active_keepers.values())
    for keeper in keepers:
        await keeper.release(
            recovery_status=RunRecoveryStatus.SHUTDOWN_REQUESTED,
            reason=reason,
        )
    return len(keepers)
