"""上游通道配额：入库不许把在线请求排到队尾。"""

from __future__ import annotations

import asyncio

import pytest

from travel_agent.config.loader import get_settings
from travel_agent.llm.router import current_llm_channel, llm_channel
from travel_agent.runtime.concurrency import (
    ChannelBusy,
    channel_gate,
    channel_metrics,
    reset_channels,
)


@pytest.fixture(autouse=True)
def _isolate_channels():
    reset_channels()
    yield
    reset_channels()


async def test_a_gate_caps_concurrency_and_reports_its_backlog():
    gate = channel_gate("test.online", 2)
    peak = 0

    async def _one() -> None:
        nonlocal peak
        async with gate.hold(wait_seconds=1.0):
            peak = max(peak, gate.active)
            await asyncio.sleep(0.02)

    await asyncio.gather(*[_one() for _ in range(6)])
    assert peak == 2
    assert channel_metrics()["test.online"]["admitted"] == 6


async def test_waiting_past_the_bound_is_a_busy_signal_not_a_hang():
    gate = channel_gate("test.bounded", 1)

    async def _hold() -> None:
        async with gate.hold(wait_seconds=1.0):
            await asyncio.sleep(0.3)

    holder = asyncio.create_task(_hold())
    await asyncio.sleep(0.02)
    with pytest.raises(ChannelBusy):
        async with gate.hold(wait_seconds=0.03):
            pass
    holder.cancel()
    with pytest.raises(asyncio.CancelledError):
        await holder


async def test_ingest_and_online_calls_do_not_share_a_quota():
    """两条路走同一个 fast 上游，但配额必须分开。

    这一条断言的是 `_channel()` 的映射本身：默认（无 contextvar）落在线档
    online_fast_llm，`llm_channel("ingest_contextual_llm")` 作用域内落入库档；
    配额都从 provider_channels 配置读取。共用一个配额时，一次上传排出的上千条
    调用会让在线请求全部排在它们后面，导致在线服务长时间不可达。
    """

    from travel_agent.llm.router import ModelTier, OpenAICompatibleLLM

    fast_llm = OpenAICompatibleLLM(
        api_key="test-key",
        model_name="test-model",
        base_url="https://openrouter.ai/api/v1",
        temperature=0,
        max_tokens=64,
        tier=ModelTier.FAST,
    )
    channels = get_settings().provider_channels

    # 默认通道按档位映射到在线档，上限读配置。
    online_gate = fast_llm._channel()
    assert online_gate.name == "llm.online_fast_llm"
    assert online_gate.limit == channels.online_fast_llm

    # 入库作用域内换到独立配额；两把 gate 身份不同、互不占用。
    with llm_channel("ingest_contextual_llm"):
        ingest_gate = fast_llm._channel()
        assert ingest_gate.name == "llm.ingest_contextual_llm"
        assert ingest_gate.limit == channels.ingest_contextual_llm
        assert ingest_gate is not online_gate
        async with ingest_gate.hold(wait_seconds=1.0):
            async with online_gate.hold(wait_seconds=0.1):
                assert ingest_gate.active == 1
                assert online_gate.active == 1
    assert ingest_gate.active == 0 and online_gate.active == 0


async def test_the_channel_override_is_scoped_to_its_block():
    with llm_channel("ingest_contextual_llm"):
        assert current_llm_channel.get() == "ingest_contextual_llm"
    assert current_llm_channel.get() is None


async def test_changing_the_limit_replaces_the_gate():
    """改配置之后旧的上限不许继续生效。"""

    first = channel_gate("test.resized", 1)
    second = channel_gate("test.resized", 4)
    assert second is not first
    assert second.limit == 4
