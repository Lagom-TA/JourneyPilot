"""把用量记录批量刷入成本台账。"""

from __future__ import annotations

import asyncio
import logging


logger = logging.getLogger(__name__)


class UsageFlushService:
    def __init__(self, recorder, store, interval=2):
        self.recorder, self.store, self.interval = recorder, store, interval
        self.task = None
        # 记录在队列里等待重试期间，同一种错误只报告一次；写入成功后重新计数。
        self._reported: set[tuple[str, str]] = set()

    def _settled(self, records) -> None:
        ids = {rec.id for rec in records}
        self._reported = {key for key in self._reported if key[0] not in ids}

    async def flush(self):
        batch = await asyncio.to_thread(self.recorder.drain)
        if not batch:
            return
        try:
            await self.store.record_calls(batch)
            await asyncio.to_thread(self.recorder.ack, batch)
            self._settled(batch)
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

        for rec in batch:
            try:
                await self.store.record_calls([rec])
                await asyncio.to_thread(self.recorder.ack, [rec])
                self._settled([rec])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                key = (rec.id, type(exc).__name__)
                if key not in self._reported:
                    self._reported.add(key)
                    logger.warning(
                        "Usage outbox retry pending call_id=%s error=%s",
                        rec.id,
                        key[1],
                    )

    def start(self):
        self.task = asyncio.create_task(self.run())

    async def run(self):
        while True:
            try:
                await self.flush()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Usage spool read failed error=%s", type(exc).__name__)
            await asyncio.sleep(self.interval)

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        try:
            async with asyncio.timeout(5):
                await self.flush()
        except Exception as exc:
            logger.warning("Usage shutdown flush pending error=%s", type(exc).__name__)
