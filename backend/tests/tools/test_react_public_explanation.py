"""ReAct 只在工具轮发布公开说明，最终轮不产生说明。"""

from __future__ import annotations

import asyncio

import pytest

from travel_agent.runtime.events import EventBuffer
from travel_agent.tools.builtin_tools import SEARCH_TOOLS_NAME, build_search_tools_item
from travel_agent.tools.react import streaming_react_loop
from travel_agent.tools.result import ReactOutcome

TOOLS = [build_search_tools_item()]


class FakeLLM:
    def __init__(self, note_received):
        self.round = 0
        self.note_received = note_received

    async def ainvoke_with_tools_events(self, messages, schemas):
        self.round += 1
        yield {"type": "stream_start", "call_id": "llm_" + str(self.round)}
        if self.round == 1:
            yield {"type": "text_delta", "content": "我先确认一下地点。"}
            yield {"type": "tool_call_delta", "content": ""}
            yield {"type": "reasoning_delta", "content": "私密推理"}
            # 消费者收到说明后才允许模型结束本轮，直接证明说明能够流式到达。
            await self.note_received.wait()
            yield {"type": "finish", "content": "我先确认一下地点。", "tool_calls": [{"id": "call_1", "name": SEARCH_TOOLS_NAME, "arguments": {"query": "博物馆"}}], "assistant_replay": {}, "call_id": "llm_1"}
        else:
            yield {"type": "text_delta", "content": "最终答案"}
            yield {"type": "finish", "content": "最终答案", "tool_calls": [], "assistant_replay": {}, "call_id": "llm_2"}


@pytest.mark.asyncio
async def test_note_is_published_before_tool_round_finishes_only():
    queue = EventBuffer()
    note_received = asyncio.Event()
    llm = FakeLLM(note_received)
    notes = []
    kinds = []

    async def consume():
        while True:
            item = await queue.get(timeout=3)
            if item[0] == "done":
                return
            kinds.append(item[0])
            if item[0] == "work_explanation":
                notes.append(item[2]["content"])
                note_received.set()

    consumer = asyncio.create_task(consume())
    try:
        result = await asyncio.wait_for(streaming_react_loop(llm, [{"role": "user", "content": "找博物馆"}], TOOLS, queue, "destination_researcher", max_iterations=3, public_note=True), timeout=3)
        await queue.put(("done",))
        await asyncio.wait_for(consumer, timeout=3)
    finally:
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)

    assert result.outcome == ReactOutcome.FINAL_ANSWER
    assert result.content == "最终答案"
    assert notes == ["我先确认一下地点。"]
    assert kinds.index("work_explanation") < kinds.index("tool_start")
