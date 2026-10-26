"""后台任务 worker：轮询数据库队列并交给领域处理器。"""

from __future__ import annotations

from travel_agent.runtime.concurrency import PeriodicTask
from travel_agent.runtime.concurrency import run_forever
from travel_agent.runtime.job_contracts import BackgroundJob
from travel_agent.runtime.job_contracts import BackgroundJobPermanentError
from travel_agent.runtime.job_contracts import BackgroundJobStatus
from travel_agent.runtime.job_contracts import BackgroundJobType
from travel_agent.runtime.job_contracts import retry_delay_seconds
from travel_agent.storage.background_job_store import BackgroundJobStore
from typing import Any
from typing import Awaitable
from typing import Callable
from typing import Dict
from typing import Optional
import asyncio
import logging
import random


logger = logging.getLogger(__name__)


JobHandler = Callable[[BackgroundJob], Awaitable[Optional[Dict[str, Any]]]]


class BackgroundJobWorker:
    """轮询 `background_jobs` 并执行任务。"""

    def __init__(
        self,
        store: BackgroundJobStore,
        handlers: Dict[BackgroundJobType, JobHandler],
        *,
        poll_seconds: float = 5.0,
        lease_seconds: int = 60,
        batch_size: int = 1,
        completed_retention_days: int = 30,
    ) -> None:
        self._store = store
        self._handlers = dict(handlers)
        self._poll_seconds = max(0.5, poll_seconds)
        self._lease_seconds = max(5, lease_seconds)
        self._batch_size = max(1, batch_size)
        self._completed_retention_days = max(1, completed_retention_days)
        self._wakeup = asyncio.Event()
        self._poller = PeriodicTask("background_jobs", self._loop)

    def notify(self) -> None:
        """有新任务入队时缩短一次等待。丢了也只影响延迟，不影响正确性。"""

        self._wakeup.set()

    def start(self) -> None:
        self._poller.start()

    async def stop(self) -> None:
        await self._poller.stop()

    async def poll_once(self) -> int:
        """领取并执行一批任务，返回执行条数。"""

        jobs = await self._store.claim(
            lease_seconds=self._lease_seconds, batch=self._batch_size
        )
        for job in jobs:
            await self._execute(job)
        return len(jobs)

    async def _loop(self) -> None:
        await run_forever("后台任务", self._step)

    async def _step(self) -> None:
        if await self.poll_once():
            return
        self._wakeup.clear()
        try:
            await asyncio.wait_for(self._wakeup.wait(), self._poll_seconds)
        except asyncio.TimeoutError:
            pass

    async def _execute(self, job: BackgroundJob) -> None:
        handler = self._handlers.get(job.job_type)
        if handler is None:
            await self._store.fail(
                job.job_id,
                error_code="no_handler",
                error_summary=f"没有注册 {job.job_type.value} 的处理器",
                retry_in_seconds=None,
            )
            return

        lease_lost = asyncio.Event()
        handler_task = asyncio.create_task(handler(job))
        renewer = asyncio.create_task(
            self._renew_lease(job.job_id, handler_task, lease_lost)
        )
        try:
            result = await handler_task
        except asyncio.CancelledError:
            if lease_lost.is_set():
                logger.warning(
                    "后台任务租约丢失，停止执行 job=%s type=%s",
                    job.job_id,
                    job.job_type.value,
                )
                return

            raise
        except BackgroundJobPermanentError as exc:
            await self._store.fail(
                job.job_id,
                error_code=exc.error_code,
                error_summary=str(exc),
                retry_in_seconds=None,
            )
            logger.warning(
                "后台任务永久失败 job=%s code=%s", job.job_id, exc.error_code
            )
            return
        except Exception as exc:
            delay = retry_delay_seconds(
                job.attempts, jitter_ratio=random.random() * 0.2
            )
            status = await self._store.fail(
                job.job_id,
                error_code=exc.__class__.__name__,
                error_summary=str(exc),
                retry_in_seconds=delay,
            )
            if status is BackgroundJobStatus.DEAD:
                logger.warning(
                    "后台任务重试用尽 job=%s type=%s error=%s",
                    job.job_id,
                    job.job_type.value,
                    exc,
                )
            else:
                logger.info(
                    "后台任务将在 %ss 后重试 job=%s attempt=%s error=%s",
                    delay,
                    job.job_id,
                    job.attempts,
                    exc,
                )
            return
        finally:
            renewer.cancel()

        await self._store.complete(job.job_id, result=result)

    async def _renew_lease(
        self,
        job_id: str,
        handler_task: asyncio.Task,
        lease_lost: asyncio.Event,
    ) -> None:
        """续租，续租失败时停止处理器。

        `renew_lease` 返回 False 表示这条任务已被另一个 worker 领走。忽略该返回值
        会让两个 worker 同时执行同一次抽取，产生重复的模型调用与画像写入。
        """

        interval = max(1.0, self._lease_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            try:
                renewed = await self._store.renew_lease(
                    job_id, lease_seconds=self._lease_seconds
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("后台任务续租失败 job=%s: %s", job_id, exc)
                continue
            if not renewed:
                lease_lost.set()
                handler_task.cancel()
                return

    async def cleanup(self) -> int:
        return await self._store.cleanup_completed(
            retention_days=self._completed_retention_days
        )
