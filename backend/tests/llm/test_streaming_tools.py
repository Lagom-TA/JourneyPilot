"""离线验证真实流式工具调用与公开说明（不请求真实模型）。"""

from __future__ import annotations

import json

import httpx
import pytest

from travel_agent.llm.chat_client import ReasoningChatOpenAI
from travel_agent.llm.router import ModelTier, OpenAICompatibleLLM

TOOLS = [{'type': 'function', 'function': {'name': 'lookup', 'parameters': {'type': 'object', 'properties': {'q': {'type': 'string'}}}}}]


def _chunk(delta, *, finish=None, usage=None):
    payload = {'id': 'chat_test', 'object': 'chat.completion.chunk', 'created': 0, 'model': 'deepseek-v4.1-flash', 'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
    if usage is not None:
        payload['usage'] = usage
    return 'data: ' + json.dumps(payload, ensure_ascii=False) + '\n\n'


def _llm(monkeypatch, client):
    import travel_agent.llm.router as router_module
    monkeypatch.setattr(router_module, "ChatOpenAI", lambda **kwargs: ReasoningChatOpenAI(**kwargs, http_async_client=client))
    return OpenAICompatibleLLM(api_key="test-key", model_name="deepseek/deepseek-v4.1-flash", base_url="https://openrouter.ai/api/v1", temperature=0.5, max_tokens=4096, timeout=5, max_retries=0, tier=ModelTier.FAST)


@pytest.mark.asyncio
async def test_streaming_tool_round_yields_real_deltas_and_replay(monkeypatch):
    args = json.dumps({"q": "青岛"}, ensure_ascii=False)
    chunks = [
        _chunk({"role": "assistant", "content": "我先确认一下地点。", "reasoning_content": "内部推理"}),
        _chunk({"content": "然后再查交通。"}),
        _chunk({"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": args[:6]}}]}),
        _chunk({"tool_calls": [{"index": 0, "function": {"arguments": args[6:]}}]}),
        _chunk({}, finish="tool_calls", usage={"prompt_tokens": 10, "completion_tokens": 12, "total_tokens": 22}),
    ]
    def respond(request):
        return httpx.Response(200, content=_sse(chunks).encode(), headers={"content-type": "text/event-stream"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        llm = _llm(monkeypatch, client)
        events = [event async for event in llm.ainvoke_with_tools_events([{"role": "user", "content": "查青岛"}], TOOLS)]
    types = [event["type"] for event in events]
    assert types[0] == "stream_start"
    text = "".join(event["content"] for event in events if event["type"] == "text_delta")
    assert text == "我先确认一下地点。然后再查交通。"
    assert "内部推理" not in text
    assert types.index("text_delta") < types.index("tool_call_delta")
    finish = events[-1]
    assert finish["tool_calls"] == [{"id": "call_1", "name": "lookup", "arguments": {"q": "青岛"}}]
    assert finish["assistant_replay"].get("reasoning_content") == "内部推理"


def _sse(chunks):
    return join_text(chunks)


def join_text(parts):
    return chr(10).join(parts)
