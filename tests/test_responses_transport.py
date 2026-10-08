"""Verify the GPT Responses and DeepSeek Chat deployment at the HTTP boundary."""

from __future__ import annotations

import json

import httpx
import pytest

from travel_agent.config import Settings
from travel_agent.models.chat_client import ReasoningChatOpenAI
from travel_agent.models.router import ModelRouter
from travel_agent.models.task_routing import TaskKind
from travel_agent.models.usage import UsageRecorder
from travel_agent.workflows.run_control import current_run_id


@pytest.fixture
def gateway_settings(monkeypatch):
    import travel_agent.models.router as router_module

    settings = Settings(
        primary_model={
            "api_key": "test-key", "model_name": "gpt-6.1-sol",
            "base_url": "http://127.0.0.1:45177/v1", "use_responses_api": True,
        },
        fast_model={
            "api_key": "test-key", "model_name": "deepseek-flash",
            "base_url": "http://127.0.0.1:45177/v1", "use_responses_api": False,
            "token_limit_field": "max_tokens",
        },
        model_pricing=[],
    )
    monkeypatch.setattr(router_module, "get_settings", lambda: settings)
    return settings


@pytest.mark.parametrize("stream,aggregate", [(False, False), (True, False), (False, True)])
async def test_primary_responses_roundtrip_and_usage(gateway_settings, monkeypatch, stream, aggregate):
    import travel_agent.models.router as router_module

    requests = []
    response = {
        "id": "resp_test", "object": "response", "created_at": 0,
        "status": "completed", "model": "gpt-6.1-sol", "error": None,
        "output": [{
            "id": "msg_test", "type": "message", "status": "completed",
            "role": "assistant", "content": [{
                "type": "output_text", "text": '{"ok":true}', "annotations": [],
            }],
        }],
        "usage": {
            "input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
            "input_tokens_details": {"cached_tokens": 40},
            "output_tokens_details": {"reasoning_tokens": 15},
        },
    }

    def respond(request):
        requests.append(request)
        if not (stream or aggregate):
            return httpx.Response(200, json=response)
        events = [
            {"type": "response.created", "response": {**response, "output": [], "usage": None}},
            {"type": "response.output_text.delta", "delta": '{"ok":true}',
             "item_id": "msg_test", "output_index": 0, "content_index": 0},
            {"type": "response.completed", "response": response},
        ]
        body = "".join("data: " + json.dumps(event) + "\n\n" for event in events)
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, text=body)

    recorder = UsageRecorder()
    gateway_settings.primary_model.responses_streaming = aggregate
    monkeypatch.setattr(router_module, "get_usage_recorder", lambda: recorder)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(router_module, "ChatOpenAI", lambda **kwargs: ReasoningChatOpenAI(
            **kwargs, http_async_client=client,
        ))
        llm = ModelRouter().get_for_task(TaskKind.COMPOSITION)
        assert llm.route.model_name == "gpt-6.1-sol"
        assert llm.route.protocol == "responses"
        messages = [{"role": "user", "content": "Return JSON with ok=true."}]
        kwargs = {"max_output_tokens": 24576, "temperature": 0,
                  "response_format": {"type": "json_object"}}
        token = current_run_id.set("run_responses_transport")
        try:
            output = ("".join([part async for part in llm.astream(messages, **kwargs)])
                      if stream else await llm.ainvoke(messages, **kwargs))
        finally:
            current_run_id.reset(token)
    assert json.loads(output) == {"ok": True}
    assert len(requests) == 1
    assert requests[0].url.path == "/v1/responses"
    wire = json.loads(requests[0].content)
    assert wire["model"] == "gpt-6.1-sol"
    assert wire["reasoning"] == {"effort": "medium"}
    assert wire["max_output_tokens"] == 24576
    assert wire["text"]["format"] == {"type": "json_object"}
    assert wire["store"] is False
    assert wire.get("stream", False) == (stream or aggregate)
    assert wire["input"][0]["role"] == "user"
    for field in ("messages", "thinking", "reasoning_effort", "max_tokens",
                  "max_completion_tokens", "temperature", "stream_options"):
        assert field not in wire
    record = recorder.snapshot()[0]
    assert (record.input_tokens, record.output_tokens, record.total_tokens) == (100, 20, 120)
    assert record.cached_input_tokens == 40
    assert record.reasoning_output_tokens == 15
    assert record.usage_complete
    assert record.stream == (stream or aggregate)


@pytest.mark.parametrize("output_limit", [None, 4096])
async def test_fast_keeps_chat_tool_transport(gateway_settings, monkeypatch, output_limit):
    import travel_agent.models.router as router_module

    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "chat_test", "object": "chat.completion", "created": 0,
            "model": "deepseek-flash", "choices": [{"index": 0, "message": {
                "role": "assistant", "content": "", "tool_calls": [{
                    "id": "call_lookup", "type": "function", "function": {
                        "name": "lookup", "arguments": '{"query":"北京"}',
                    },
                }],
            }, "finish_reason": "tool_calls"}],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(router_module, "ChatOpenAI", lambda **kwargs: ReasoningChatOpenAI(
            **kwargs, http_async_client=client,
        ))
        llm = ModelRouter().get_for_task(TaskKind.RESEARCH_TOOLS, has_tools=True)
        assert llm.route.model_name == "deepseek-flash"
        assert llm.route.protocol == "chat_completions"
        tools = [{"type": "function", "function": {"name": "lookup", "parameters": {
            "type": "object", "properties": {"query": {"type": "string"}},
        }}}]
        result = await llm.ainvoke_with_tools(
            [{"role": "user", "content": "查北京"}], tools,
            max_output_tokens=output_limit,
        )
    assert result["tool_calls"][0]["name"] == "lookup"
    assert requests[0].url.path == "/v1/chat/completions"
    wire = json.loads(requests[0].content)
    assert wire["model"] == "deepseek-flash"
    assert wire["reasoning_effort"] == "low"
    assert wire["max_tokens"] == (output_limit or gateway_settings.fast_model.max_tokens)
    assert "max_completion_tokens" not in wire
    assert "input" not in wire


@pytest.mark.parametrize("stream,terminal", [(False, "incomplete"), (True, "incomplete"), (True, None)])
async def test_incomplete_responses_fail_without_losing_reported_usage(gateway_settings, monkeypatch, stream, terminal):
    import travel_agent.models.router as router_module

    response = {
        "id": "resp_incomplete", "object": "response", "created_at": 0,
        "status": "incomplete", "model": "gpt-6.1-sol", "error": None,
        "incomplete_details": {"reason": "max_output_tokens"},
        "output": [{"id": "msg_partial", "type": "message", "status": "incomplete",
                    "role": "assistant", "content": [{"type": "output_text", "text": '{"ok":', "annotations": []}]}],
        "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
                  "input_tokens_details": {"cached_tokens": 0},
                  "output_tokens_details": {"reasoning_tokens": 15}},
    }

    def respond(request):
        if not stream:
            return httpx.Response(200, json=response)
        events = [
            {"type": "response.created", "response": {**response, "status": "in_progress", "output": [], "usage": None}},
            {"type": "response.output_text.delta", "delta": '{"ok":',
             "item_id": "msg_partial", "output_index": 0, "content_index": 0},
        ]
        if terminal:
            events.append({"type": "response.incomplete", "response": response})
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"},
                              text="".join("data: " + json.dumps(event) + "\n\n" for event in events))

    recorder = UsageRecorder()
    monkeypatch.setattr(router_module, "get_usage_recorder", lambda: recorder)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(router_module, "ChatOpenAI", lambda **kwargs: ReasoningChatOpenAI(**kwargs, http_async_client=client))
        llm = ModelRouter().get_for_task(TaskKind.COMPOSITION)
        token = current_run_id.set("run_incomplete_response")
        try:
            with pytest.raises(router_module.IncompleteModelResponse):
                if stream:
                    async for _ in llm.astream([{"role": "user", "content": "Return JSON."}]):
                        pass
                else:
                    await llm.ainvoke([{"role": "user", "content": "Return JSON."}])
        finally:
            current_run_id.reset(token)
    record, = recorder.snapshot()
    assert record.status == "error"
    assert record.estimated is False
    if terminal:
        assert (record.input_tokens, record.output_tokens, record.total_tokens) == (100, 20, 120)
        assert record.finish_reason == "length"
        assert record.usage_complete
    else:
        assert record.input_tokens is None and record.output_tokens is None
        assert record.usage_source == "missing"
