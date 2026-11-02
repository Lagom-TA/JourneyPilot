"""在 HTTP 边界验证 GPT Responses 与 DeepSeek Chat 部署。"""

from __future__ import annotations

import json

import httpx
import pytest

from travel_agent.config.models import Settings
from travel_agent.llm.chat_client import ReasoningChatOpenAI
from travel_agent.llm.router import ModelRouter
from travel_agent.llm.task_routing import TaskKind
from travel_agent.llm.usage import UsageRecorder
from travel_agent.runtime.context import current_run_id


@pytest.fixture
def gateway_settings(monkeypatch):
    import travel_agent.llm.router as router_module

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


@pytest.mark.parametrize("stream", [False, True])
async def test_deadline_rejection_before_first_provider_call_has_no_usage_attempt(
    gateway_settings, monkeypatch, tmp_path, stream,
):
    import travel_agent.llm.router as router_module
    import travel_agent.runtime.operations as control_module
    from travel_agent.runtime.deadlines import DeadlineObservation
    from travel_agent.runtime.operations import ModelWindowClosed

    requests = []
    recorder = UsageRecorder(spool_path=tmp_path / "usage.sqlite3")
    monkeypatch.setattr(router_module, "get_usage_recorder", lambda: recorder)

    def closed(operation):
        raise ModelWindowClosed(operation, DeadlineObservation(1000, 0, "expired"), "research")

    monkeypatch.setattr(router_module, "remaining_model_seconds", closed)
    monkeypatch.setattr(control_module, "remaining_model_seconds", closed)

    def respond(request):
        requests.append(request)
        raise AssertionError("expired operations must not reach the provider")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(router_module, "ChatOpenAI", lambda **kwargs: ReasoningChatOpenAI(
            **kwargs, http_async_client=client,
        ))
        llm = ModelRouter().get_for_task(TaskKind.COMPOSITION)
        token = current_run_id.set("run_expired_before_provider")
        try:
            with pytest.raises(ModelWindowClosed):
                if stream:
                    async for _ in llm.astream([{"role": "user", "content": "Return JSON."}]):
                        pass
                else:
                    await llm.ainvoke([{"role": "user", "content": "Return JSON."}])
        finally:
            current_run_id.reset(token)
    assert requests == []
    assert recorder.drain() == []
    assert recorder._spool.db.execute("SELECT COUNT(*) FROM usage_outbox").fetchone()[0] == 0


@pytest.mark.parametrize("stream,aggregate", [(False, False), (True, False), (False, True)])
async def test_primary_responses_roundtrip_and_usage(gateway_settings, monkeypatch, stream, aggregate):
    import travel_agent.llm.router as router_module

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
    import travel_agent.llm.router as router_module

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


async def test_chat_completion_retries_provider_error_instead_of_accepting_partial_output(
    gateway_settings, monkeypatch,
):
    import travel_agent.llm.router as router_module

    requests = []

    def respond(request):
        requests.append(request)
        failed = len(requests) == 1
        return httpx.Response(200, json={
            "id": f"chat_{len(requests)}", "object": "chat.completion", "created": 0,
            "model": "deepseek-flash", "choices": [{"index": 0, "message": {
                "role": "assistant", "content": '{"partial":' if failed else '{"ok":true}',
            }, "finish_reason": "error" if failed else "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })

    recorder = UsageRecorder()
    monkeypatch.setattr(router_module, "get_usage_recorder", lambda: recorder)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(router_module, "ChatOpenAI", lambda **kwargs: ReasoningChatOpenAI(
            **kwargs, http_async_client=client,
        ))
        llm = ModelRouter().get_for_task(TaskKind.RESEARCH_TOOLS, has_tools=True)
        token = current_run_id.set("run_chat_retry")
        try:
            result = await llm.ainvoke_with_tools([{"role": "user", "content": "Return JSON."}], [])
        finally:
            current_run_id.reset(token)
    assert json.loads(result["content"]) == {"ok": True}
    assert len(requests) == 2
    first, second = recorder.snapshot()
    assert (first.status, first.finish_reason, first.attempt_number) == ("error", "error", 1)
    assert (second.status, second.finish_reason, second.attempt_number) == ("ok", "stop", 2)
    assert first.logical_call_id == second.logical_call_id


@pytest.mark.parametrize("stream,terminal", [(False, "incomplete"), (True, "incomplete"), (True, None)])
async def test_incomplete_responses_fail_without_losing_reported_usage(gateway_settings, monkeypatch, stream, terminal):
    import travel_agent.llm.router as router_module

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


async def test_understanding_full_tool_round_on_the_strong_responses_model(
    gateway_settings, monkeypatch,
):
    """理解角色的完整回合：强模型选中 → 返回工具调用 → 结果回传同一模型 → 得出结论。

    primary 配置为 Responses 协议的 gpt-6.1-sol；这条链路过去会被静默降档或
    直接拒绝，现在必须原档完成。
    """

    import travel_agent.llm.router as router_module

    requests = []
    first_response = {
        "id": "resp_tool", "object": "response", "created_at": 0,
        "status": "completed", "model": "gpt-6.1-sol", "error": None,
        "output": [{
            "type": "function_call", "id": "fc_1", "call_id": "call_lookup",
            "name": "lookup", "arguments": '{"query":"青岛 11 月"}', "status": "completed",
        }],
        "usage": {
            "input_tokens": 50, "output_tokens": 10, "total_tokens": 60,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }
    final_response = {
        "id": "resp_final", "object": "response", "created_at": 0,
        "status": "completed", "model": "gpt-6.1-sol", "error": None,
        "output": [{
            "id": "msg_final", "type": "message", "status": "completed",
            "role": "assistant", "content": [{
                "type": "output_text",
                "text": '{"action":"ask","questions":[{"id":"pace","question":"节奏？","kind":"single","options":[]}]}',
                "annotations": [],
            }],
        }],
        "usage": {
            "input_tokens": 90, "output_tokens": 30, "total_tokens": 120,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 5},
        },
    }

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=first_response if len(requests) == 1 else final_response)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(router_module, "ChatOpenAI", lambda **kwargs: ReasoningChatOpenAI(
            **kwargs, http_async_client=client,
        ))
        llm = ModelRouter().get_for_task(TaskKind.UNDERSTANDING, has_tools=True)
        # 没有静默降档：强模型与 Responses 协议原样保留。
        assert llm.route.tier == "primary"
        assert llm.route.model_name == "gpt-6.1-sol"
        assert llm.route.protocol == "responses"

        tools = [{"type": "function", "function": {"name": "lookup", "parameters": {
            "type": "object", "properties": {"query": {"type": "string"}},
        }}}]
        messages = [{"role": "user", "content": "想去青岛放松几天"}]
        first = await llm.ainvoke_with_tools(messages, tools)
        assert first["tool_calls"][0]["name"] == "lookup"

        # 离线工具执行完毕，把结果回传给同一个强模型。
        messages.append({
            "role": "assistant", "content": first["content"],
            "tool_calls": first["tool_calls"],
        })
        messages.append({
            "role": "tool", "tool_call_id": first["tool_calls"][0]["id"],
            "content": '{"results":["青岛 11 月适合散步"]}',
        })
        final = await llm.ainvoke_with_tools(messages, tools)

    assert final["tool_calls"] == []
    assert '"action":"ask"' in final["content"]
    assert [request.url.path for request in requests] == ["/v1/responses", "/v1/responses"]
    first_wire = json.loads(requests[0].content)
    assert first_wire["tools"][0]["type"] == "function"
    assert first_wire["tools"][0]["name"] == "lookup"
    second_wire = json.loads(requests[1].content)
    input_items = second_wire["input"]
    assert any(item.get("type") == "function_call" and item.get("call_id") == "call_lookup"
               for item in input_items)
    assert any(item.get("type") == "function_call_output" and "青岛 11 月适合散步" in str(item.get("output"))
               for item in input_items)
