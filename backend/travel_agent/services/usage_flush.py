"""Drain the local outbox independently of SSE clients and active runs."""
import asyncio
import logging

logger = logging.getLogger(__name__)


class UsageFlushService:
    def __init__(self, recorder, store, interval=2):
        self.recorder, self.store, self.interval = recorder, store, interval
        self.task = None

    async def flush(self):
        batch = self.recorder.drain()
        if not batch:
            return
        try:
            await self.store.record_calls(batch)
            self.recorder.ack(batch)
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        # Isolate conflicting/orphaned rows: a single poison record must never
        # block billing for unrelated runs. Successful rows are acked individually.
        for rec in batch:
            try:
                await self.store.record_calls([rec])
                self.recorder.ack([rec])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Usage outbox retry pending call_id=%s error=%s", rec.id, type(exc).__name__)

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
