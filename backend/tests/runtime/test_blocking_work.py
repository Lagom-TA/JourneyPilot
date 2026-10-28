"""同步工作隔离：通道上限、排队上界、Event Loop 不被占住。"""

from __future__ import annotations

import asyncio
import time

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
    import threading

    limits.document_parse = 2
    peak = 0
    in_flight = 0
    guard = threading.Lock()

    def _work() -> None:
        # 在线程体内记录真实并发峰值，这才会被通道上限挡住。
        nonlocal in_flight
        with guard:
            in_flight += 1
        time.sleep(0.05)
        with guard:
            in_flight -= 1

    def _snapshot_peak() -> None:
        nonlocal peak
        for _ in range(80):
            with guard:
                peak = max(peak, in_flight)
            time.sleep(0.005)

    async def _one() -> None:
        await run_blocking("document_parse", _work)

    # 六个请求、上限两个：通道把线程内并发压到 2，而不是 6 个一起进线程池。
    # watcher 每 5ms 采样一次 in_flight，持续 0.4s，覆盖全部六次调度的窗口。
    watcher = asyncio.get_running_loop().run_in_executor(None, _snapshot_peak)
    done, _ = await asyncio.wait(
        [asyncio.gather(*[_one() for _ in range(6)])], timeout=0.5,
    )
    assert done
    await watcher
    assert blocking_work_metrics()["document_parse"]["admitted"] == 6
    assert blocking_work_metrics()["document_parse"]["limit"] == 2
    assert 0 < peak <= 2


async def test_queue_wait_has_an_upper_bound(limits):
    limits.pdf_export = 1
    limits.queue_wait_seconds = 0.05

    async def _hold() -> None:
        async with blocking_channel("pdf_export"):
            await asyncio.sleep(0.4)

    holder = asyncio.create_task(_hold())
    await asyncio.sleep(0.02)
    with pytest.raises(BlockingWorkBusy) as exc:
        await run_blocking("pdf_export", lambda: None)
    assert exc.value.channel == "pdf_export"
    assert blocking_work_metrics()["pdf_export"]["busy_rejections"] == 1
    holder.cancel()
    with pytest.raises(asyncio.CancelledError):
        await holder


async def test_blocking_call_does_not_stall_the_event_loop(limits):
    """一次 0.3 秒的同步调用期间，Event Loop 上的心跳必须继续跳。

    这就是「PDF 不阻塞 Event Loop」那句话可以被机械验证的形式：不断言 PDF 的内容，
    断言的是**另一个协程在这期间还能跑**。
    """

    ticks = 0

    async def _heartbeat() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    beat = asyncio.create_task(_heartbeat())
    await run_blocking("pdf_export", time.sleep, 0.3)
    beat.cancel()
    assert ticks >= 5


async def test_a_thread_call_keeps_its_contextvars():
    """run 归因要能进线程：否则线程里的记账与日志全部落在 unknown 上。"""

    from travel_agent.runtime.context import current_run_id

    token = current_run_id.set("run_blocking_ctx")
    try:
        seen = await run_blocking("pdf_export", current_run_id.get)
    finally:
        current_run_id.reset(token)
    assert seen == "run_blocking_ctx"
