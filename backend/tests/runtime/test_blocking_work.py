"""同步工作隔离：通道上限、排队上界、Event Loop 不被占住。"""

from __future__ import annotations

import asyncio
import threading

import pytest

from travel_agent.config.loader import get_settings
from travel_agent.runtime.blocking_work import (
    BlockingWorkBusy,
    blocking_channel,
    blocking_work_metrics,
    run_blocking,
)
from travel_agent.runtime.concurrency import reset_channels


@pytest.fixture(autouse=True)
def _isolate_channels():
    reset_channels()
    yield
    reset_channels()


@pytest.fixture
def limits():
    """把上限调小到能在测试里观察，跑完还原。"""

    config = get_settings().blocking_work
    original = config.model_dump()
    yield config
    for key, value in original.items():
        setattr(config, key, value)


async def test_unknown_channel_is_rejected_rather_than_run_unbounded():
    with pytest.raises(ValueError, match="unknown blocking work channel"):
        await run_blocking("not_a_channel", lambda: None)


async def test_channel_limit_caps_concurrent_thread_work(limits):
    limits.document_parse = 2
    limits.queue_wait_seconds = 0.05
    loop = asyncio.get_running_loop()
    full = asyncio.Event()
    release = threading.Event()
    peak = 0
    in_flight = 0
    guard = threading.Lock()

    def _work() -> None:
        nonlocal in_flight, peak
        with guard:
            in_flight += 1
            peak = max(peak, in_flight)
            if in_flight == 2:
                loop.call_soon_threadsafe(full.set)
        try:
            assert release.wait(timeout=3), "测试结束时必须释放线程"
        finally:
            with guard:
                in_flight -= 1

    tasks = [asyncio.create_task(run_blocking("document_parse", _work)) for _ in range(2)]
    try:
        await asyncio.wait_for(full.wait(), timeout=3)
        # 两个真实线程持续占用通道，第三个请求必须按排队预算拒绝。
        with pytest.raises(BlockingWorkBusy):
            await run_blocking("document_parse", lambda: None)
    finally:
        release.set()
        await asyncio.gather(*tasks)

    assert peak == 2 and in_flight == 0
    assert await run_blocking("document_parse", lambda: "released") == "released"
    assert blocking_work_metrics()["document_parse"]["admitted"] == 3
    assert blocking_work_metrics()["document_parse"]["limit"] == 2


async def test_queue_wait_has_an_upper_bound(limits):
    limits.pdf_export = 1
    limits.queue_wait_seconds = 0.05
    held = asyncio.Event()

    async def _hold() -> None:
        async with blocking_channel("pdf_export"):
            held.set()
            await asyncio.Event().wait()

    holder = asyncio.create_task(_hold())
    try:
        await asyncio.wait_for(held.wait(), timeout=3)
        with pytest.raises(BlockingWorkBusy) as exc:
            await run_blocking("pdf_export", lambda: None)
    finally:
        holder.cancel()
        await asyncio.gather(holder, return_exceptions=True)
    assert exc.value.channel == "pdf_export"
    assert blocking_work_metrics()["pdf_export"]["busy_rejections"] == 1
    assert await run_blocking("pdf_export", lambda: "released") == "released"


async def test_blocking_call_does_not_stall_the_event_loop(limits):
    """同步工作等待 Event Loop 发出释放信号，证明另一个协程能够继续执行。"""

    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()

    async def _heartbeat() -> None:
        await started.wait()
        release.set()

    def _work() -> bool:
        loop.call_soon_threadsafe(started.set)
        return release.wait(timeout=3)

    beat = asyncio.create_task(_heartbeat())
    try:
        released_by_loop = await run_blocking("pdf_export", _work)
    finally:
        release.set()
        beat.cancel()
        await asyncio.gather(beat, return_exceptions=True)
    assert released_by_loop is True


async def test_a_thread_call_keeps_its_contextvars():
    """run 归因要能进线程：否则线程里的记账与日志全部落在 unknown 上。"""

    from travel_agent.runtime.context import current_run_id

    token = current_run_id.set("run_blocking_ctx")
    try:
        seen = await run_blocking("pdf_export", current_run_id.get)
    finally:
        current_run_id.reset(token)
    assert seen == "run_blocking_ctx"
