"""Request-level reasoning and output budgets, verified without paid API calls."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from langchain_core.messages import HumanMessage

from travel_agent.config import FastModelConfig, PrimaryModelConfig
from travel_agent.models.chat_client import ReasoningChatOpenAI
from travel_agent.models.request_policy import is_openai_reasoning_model, model_reasoning_effort
from travel_agent.models.router import ModelTier, OpenAICompatibleLLM, _to_langchain_messages


@pytest.mark.parametrize("name", ["gpt-6.1-sol", "openai/gpt-6.1-sol", "GPT-6.1-SOL"])
def test_primary_reasoning_does_not_send_unsupported_sampling(name):
    llm = OpenAICompatibleLLM(
        api_key="test-key", model_name=name, base_url="https://openrouter.ai/api/v1",
        temperature=0.7, max_tokens=24576, tier=ModelTier.PRIMARY,
    )
    kwargs, limit = llm._apply_output_token_limit({"temperature": 0, "max_output_tokens": 24576})
    payload = llm._client._get_request_payload([HumanMessage(content="Plan")], **kwargs)
    assert "temperature" not in payload
    assert payload["reasoning_effort"] == "medium"
    assert payload["extra_body"]["reasoning"] == {"effort": "medium", "enabled": True}
    assert payload["max_completion_tokens"] == limit == 24576


def test_tier_defaults_and_deepseek_medium_alias():
    assert PrimaryModelConfig().reasoning_effort == "medium"
    assert FastModelConfig().reasoning_effort == "low"
    assert model_reasoning_effort("deepseek/deepseek-v4.1-flash", "medium") == "low"
    assert not is_openai_reasoning_model("deepseek/deepseek-v4.1-flash")
    with pytest.raises(ValueError):
        model_reasoning_effort("openai/gpt-6.1-sol", "none")


def test_none_output_overrides_use_the_deployment_default_without_sending_null_keys():
    llm = OpenAICompatibleLLM(
        api_key="test-key", model_name="deepseek-v4.1-flash", base_url="https://api.deepseek.com",
        temperature=0, max_tokens=65536, tier=ModelTier.FAST,
    )
    kwargs, limit = llm._apply_output_token_limit({
        "max_output_tokens": None, "max_tokens": None, "max_completion_tokens": None,
    })
    assert kwargs == {} and limit == 65536


@pytest.mark.asyncio
async def test_reasoning_replays_across_a_complete_tool_call_round(monkeypatch):
    import travel_agent.models.router as router_module

    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        message = (
            {"role": "assistant", "content": "", "reasoning_content": "opaque thinking",
             "reasoning_details": [{"type": "reasoning.text", "text": "retained"}],
             "tool_calls": [{"id": "call_lookup", "type": "function", "function": {
                 "name": "lookup", "arguments": '{"query":"北京"}'}}]}
            if len(requests) == 1 else {"role": "assistant", "content": "完成"}
        )
        return httpx.Response(200, json={
            "id": "chat_test", "object": "chat.completion", "created": 0,
            "model": "deepseek-v4.1-flash", "choices": [{"index": 0, "message": message,
                "finish_reason": "tool_calls" if len(requests) == 1 else "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(router_module, "ChatOpenAI", lambda **kwargs: ReasoningChatOpenAI(
            **kwargs, http_async_client=client,
        ))
        llm = OpenAICompatibleLLM(
            api_key="test-key", model_name="deepseek/deepseek-v4.1-flash",
            base_url="https://openrouter.ai/api/v1", temperature=0.5,
            max_tokens=16384, timeout=5, max_retries=0, tier=ModelTier.FAST,
        )
        tools = [{"type": "function", "function": {"name": "lookup", "parameters": {
            "type": "object", "properties": {"query": {"type": "string"}}}}}]
        messages = [{"role": "user", "content": "查北京"}]
        first = await asyncio.wait_for(llm.ainvoke_with_tools(messages, tools), timeout=10)
        messages.extend([
            {"role": "assistant", "content": first["content"], "tool_calls": first["tool_calls"],
             "assistant_replay": first["assistant_replay"]},
            {"role": "tool", "tool_call_id": "call_lookup", "content": '{"found":true}'},
        ])
        second = await asyncio.wait_for(llm.ainvoke_with_tools(messages, tools), timeout=10)
        assert second["content"] == "完成"
        wire = requests[1]["messages"][1]
        assert wire["reasoning_content"] == "opaque thinking"
        assert wire["reasoning_details"] == [{"type": "reasoning.text", "text": "retained"}]
        assert requests[1]["reasoning"] == {"effort": "low", "enabled": True}
        assert requests[1]["max_tokens"] == requests[1]["max_completion_tokens"] == 16384
        assert _to_langchain_messages(messages)[1].content == ""


def test_snapshot_tools_never_replay_local_envelopes():
    from travel_agent.agents.utils import _NO_CACHE_TOOLS
    from travel_agent.infrastructure.provider_snapshot_cache import _SUPPORTED_TOOLS

    assert _SUPPORTED_TOOLS <= _NO_CACHE_TOOLS
