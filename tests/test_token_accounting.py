"""Usage, billing and request attempts, without a paid model call."""

from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessageChunk

from travel_agent.config import ModelPricingItem, RunBudgetConfig
from travel_agent.entities.run_budget import RunBudgetSnapshot, RunBudgetUsage, exhausted_dimension, remaining_budget
from travel_agent.infrastructure.cost_ledger_store import (
    CostLedgerConflict, InMemoryCostLedgerStore, build_ledger_call, compute_cost_usd, summarize_calls,
)
from travel_agent.models.chat_client import ReasoningChatOpenAI
from travel_agent.models.router import ModelTier, OpenAICompatibleLLM
from travel_agent.models.token_counting import estimate_message_tokens, estimate_request_tokens, estimate_tokens
from travel_agent.models.usage import LLMCallRecord, UsageRecorder, error_usage_message, extract_usage, response_finish_reason
from travel_agent.workflows.run_budget import RunBudgetLedger
from travel_agent.workflows.run_control import current_run_id


@pytest.mark.parametrize("raw, expected", [
    ({"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
      "prompt_tokens_details": {"cached_tokens": 40, "cache_write_tokens": 30},
      "completion_tokens_details": {"reasoning_tokens": 15}}, (100, 20, 40, 30, 15)),
    ({"input_tokens": 100, "output_tokens": 20,
      "input_tokens_details": {"cached_tokens": 40, "cache_write_tokens": 30},
      "output_tokens_details": {"reasoning_tokens": 15}}, (100, 20, 40, 30, 15)),
    ({"prompt_tokens": 100, "completion_tokens": 20, "prompt_cache_hit_tokens": 40,
      "prompt_cache_miss_tokens": 60}, (100, 20, 40, None, None)),
    ({"input_tokens": 30, "output_tokens": 20, "cache_read_input_tokens": 40,
      "cache_creation_input_tokens": 30}, (100, 20, 40, 30, None)),
])
def test_raw_usage_is_not_lost_when_standard_mapping_is_missing(raw, expected):
    result = extract_usage(SimpleNamespace(response_metadata={"token_usage": raw}))
    assert tuple(result[key] for key in (
        "input_tokens", "output_tokens", "cached_input_tokens", "cache_write_input_tokens", "reasoning_output_tokens"
    )) == expected
    assert result["total_tokens"] == 120


def test_standard_inclusive_cache_buckets_are_not_added_twice():
    result = extract_usage(SimpleNamespace(
        usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
                        "input_token_details": {"cache_read": 40, "cache_creation": 30}},
        response_metadata={"usage": {"input_tokens": 30, "output_tokens": 20,
                                    "cache_read_input_tokens": 40, "cache_creation_input_tokens": 30}},
    ))
    assert result["input_tokens"] == 100
    assert result["total_tokens"] == 120


def test_zero_standard_placeholders_do_not_overwrite_raw_counts():
    result = extract_usage(SimpleNamespace(
        usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        response_metadata={"usage": {"prompt_tokens": 10, "completion_tokens": 5}},
    ))
    assert result["total_tokens"] == 15


def test_exclusive_raw_cache_buckets_override_zero_mapping_placeholders():
    result = extract_usage(SimpleNamespace(
        usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        response_metadata={"usage": {"input_tokens": 30, "output_tokens": 20,
                                    "cache_read_input_tokens": 40, "cache_creation_input_tokens": 30}},
    ))
    assert result["input_tokens"] == 100
    assert result["total_tokens"] == 120


@pytest.mark.parametrize("raw", [
    {"prompt_tokens": 100, "total_tokens": 120},
    {"completion_tokens": 20, "total_tokens": 120},
])
def test_raw_total_recovers_a_side_hidden_by_standard_zero_placeholders(raw):
    result = extract_usage(SimpleNamespace(
        usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        response_metadata={"usage": raw},
    ))
    assert (result["input_tokens"], result["output_tokens"], result["total_tokens"]) == (100, 20, 120)


def test_explicit_raw_zero_output_is_preserved():
    result = extract_usage({"response_metadata": {"usage": {
        "prompt_tokens": 100, "completion_tokens": 0, "total_tokens": 100,
    }}})
    assert result["output_tokens"] == 0


def test_conflicting_returned_total_is_incomplete_in_the_record_and_summary():
    message = {"response_metadata": {"usage": {
        "prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 999,
    }}}
    usage = extract_usage(message)
    assert usage["total_tokens"] == 120
    assert not usage["usage_complete"]
    recorder = UsageRecorder()
    llm = _llm(recorder)
    llm._emit(_record(), 0, message=message)
    record = recorder.snapshot()[0]
    assert not record.usage_complete and record.usage_source == "partial"
    summary = summarize_calls(record.run_id, [build_ledger_call(record)])
    assert not summary["token_usage_complete"]


def test_malformed_raw_detail_shape_does_not_break_usage_capture():
    usage = extract_usage({"response_metadata": {"usage": {
        "prompt_tokens": 100, "completion_tokens": 20,
        "prompt_tokens_details": ["invalid"], "completion_tokens_details": "invalid",
    }}})
    assert usage["input_tokens"] == 100 and usage["output_tokens"] == 20
    assert usage["cached_input_tokens"] is None
    assert usage["reasoning_output_tokens"] is None


@pytest.mark.parametrize("value", [-1, True, 1.5, "invalid", float("inf")])
def test_malformed_counts_are_unknown_not_negative_or_fractional_tokens(value):
    result = extract_usage({"usage_metadata": {"input_tokens": value, "output_tokens": 20}})
    assert result["input_tokens"] is None


def _price():
    return ModelPricingItem(pattern="test", input_per_1m=2, cached_input_per_1m=0.1,
                            cache_write_per_1m=2.5, output_per_1m=10)


def test_disjoint_cache_buckets_and_inclusive_reasoning_have_one_bill():
    price = _price()
    # 30k ordinary + 40k cached + 30k written + 20k completion (contains reasoning).
    cost = compute_cost_usd(price, input_tokens=100000, output_tokens=20000,
                            cached_input_tokens=40000, cache_write_input_tokens=30000)
    assert cost == pytest.approx(0.339)
    assert compute_cost_usd(price, input_tokens=100000, output_tokens=0,
                            cached_input_tokens=0, cache_write_input_tokens=100000) == 0.25


@pytest.mark.parametrize("read,write", [(101, 0), (80, 30)])
def test_invalid_cache_buckets_do_not_produce_a_hit_ratio(read, write):
    call = build_ledger_call(_record(cached_input_tokens=read, cache_write_input_tokens=write), pricing=[_price()])
    assert summarize_calls(call.run_id, [call])["cache_hit_ratio"] is None


@pytest.mark.parametrize("inp,out,read,write", [
    (None, 100, 0, 0), (100, None, 0, 0), (100, 20, 80, 30),
    (100, 20, 0, None), (100, 20, None, 0),
    (-1, 20, 0, 0), (100, -1, 0, 0), (100, 20, -1, 0), (100, 20, 0, -1),
    (True, 20, 0, 0), (100, 1.5, 0, 0),
])
def test_unknown_or_invalid_usage_does_not_become_a_complete_price(inp, out, read, write):
    assert compute_cost_usd(_price(), input_tokens=inp, output_tokens=out,
                            cached_input_tokens=read, cache_write_input_tokens=write) is None


def _record(**changes):
    fields = dict(id="call_1", run_id="run_usage", node="worker", agent="worker", tier="fast",
                  provider="", model_request="test", method="ainvoke", stream=False,
                  start_ts="2026-10-05T00:00:00+00:00", input_tokens=100, output_tokens=20,
                  total_tokens=120, cached_input_tokens=40, cache_write_input_tokens=30,
                  reasoning_output_tokens=15)
    return LLMCallRecord(**(fields | changes))


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "cached_input_tokens",
                                  "cache_write_input_tokens", "reasoning_output_tokens", "total_tokens"])
@pytest.mark.parametrize("value", [-1, True, 1.5, "invalid"])
def test_malformed_record_cannot_become_a_complete_ledger_bill(field, value):
    call = build_ledger_call(_record(**{field: value}), pricing=[_price()])
    assert call.cost_usd is None
    assert not call.usage_complete
    assert call.usage_source == "partial"
    if field != "total_tokens":
        assert getattr(call, field) is None


async def test_persisted_details_survive_replay_and_invalid_replay_is_rejected():
    store = InMemoryCostLedgerStore()
    record = _record(logical_call_id="logical", attempt_number=2,
                     request_input_tokens_estimate=200, tool_schema_tokens_estimate=50)
    await store.record_calls([record], pricing=[_price()])
    await store.record_calls([record], pricing=[_price()])
    calls = await store.list_calls("run_usage")
    assert len(calls) == 1
    assert calls[0].cache_write_input_tokens == 30
    assert calls[0].attempt_number == 2
    with pytest.raises(CostLedgerConflict):
        await store.record_calls([replace(record, cache_write_input_tokens=31)], pricing=[_price()])


def test_partial_summary_is_explicit_and_does_not_add_reasoning_twice():
    calls = [build_ledger_call(_record(), pricing=[_price()]), build_ledger_call(
        _record(id="call_2", input_tokens=None, output_tokens=None, total_tokens=None,
                cached_input_tokens=None, cache_write_input_tokens=None,
                reasoning_output_tokens=None, usage_complete=False, usage_source="missing"), pricing=[_price()])]
    result = summarize_calls("run_usage", calls)
    assert result["total_tokens"] == 120
    assert result["total_cache_write_input_tokens"] == 30
    assert result["token_usage_complete"] is False
    assert result["cost_complete"] is False
    assert result["missing_usage_call_count"] == 1
    assert result["cost_coverage_ratio"] == 0.5


def test_entirely_unknown_usage_stays_null_in_summary_and_node_totals():
    call = build_ledger_call(_record(input_tokens=None, output_tokens=None, total_tokens=None,
                                    cached_input_tokens=None, cache_write_input_tokens=None,
                                    reasoning_output_tokens=None, usage_complete=False, usage_source="missing"))
    summary = summarize_calls("run_usage", [call])
    assert summary["total_input_tokens"] is None
    assert summary["total_output_tokens"] is None
    assert summary["total_tokens"] is None
    assert summary["total_cached_input_tokens"] is None
    assert summary["total_cache_write_input_tokens"] is None
    assert summary["by_node"][0]["total_tokens"] is None


def test_truncated_structured_output_keeps_the_sdk_completion_usage():
    from openai import LengthFinishReasonError
    from openai.types.chat import ChatCompletion

    completion = ChatCompletion.model_validate({
        "id": "truncated", "object": "chat.completion", "created": 0, "model": "test",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "{"}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    })
    usage = extract_usage(error_usage_message(LengthFinishReasonError(completion=completion)))
    assert usage["total_tokens"] == 150
    assert response_finish_reason(error_usage_message(LengthFinishReasonError(completion=completion))) == "length"


def test_all_text_estimates_use_one_offline_ruler_and_include_wire_fields():
    from travel_agent.memory.compressor import _count_tokens
    from travel_agent.memory.context_builder import count_tokens

    for text in ["", "北京上海", "hello world", "emoji 🧭"]:
        assert count_tokens(text) == _count_tokens(text) == estimate_tokens(text)
    assert estimate_tokens("") == 0
    assert estimate_tokens("北京上海") >= 4
    message = {"role": "assistant", "content": "", "reasoning_content": "opaque retained",
               "tool_calls": [{"function": {"name": "lookup", "arguments": '{"city":"北京"}'}}]}
    assert estimate_message_tokens(message) > estimate_tokens(message["content"])
    plain, _ = estimate_request_tokens({"messages": [message]})
    with_tools, schemas = estimate_request_tokens({"messages": [message], "tools": [{"name": "lookup"}],
                                                  "response_format": {"type": "json_schema", "schema": {"type": "object"}}})
    assert with_tools > plain and schemas > 0


def test_unlimited_default_and_legacy_snapshot_keep_accounting_without_rejection():
    assert RunBudgetConfig().enforce_limits is False
    assert RunBudgetConfig().max_input_tokens is None
    snapshot = RunBudgetSnapshot(max_llm_calls=1, max_input_tokens=1, max_cost_usd=0.01,
                                 max_tool_retries_per_target=1)
    ledger = RunBudgetLedger("run_unlimited", snapshot)
    for _ in range(3):
        ledger.record_llm_call(input_tokens=10000000, output_tokens=1000000, cost_usd=10)
        ledger.reserve_tool_call("tool", "lookup")
        ledger.record_tool_retry("lookup")
    ledger.guard("model", llm_calls=1, input_tokens=100000000, output_tokens=100000000)
    assert ledger.usage().llm_calls == 3
    assert ledger.usage().input_tokens == 30000000
    assert not ledger.tool_retries_exhausted("lookup")
    assert exhausted_dimension(snapshot, RunBudgetUsage(cost_usd=100)) is None
    assert all(value is None for value in remaining_budget(snapshot, ledger.usage()).values())


def _llm(recorder):
    return OpenAICompatibleLLM(api_key="test", model_name="deepseek-v4.1-flash",
                               base_url="https://api.deepseek.com", temperature=0.5,
                               max_tokens=65536, tier=ModelTier.FAST, usage_recorder=recorder)


async def test_stream_uses_the_last_cumulative_usage_sample(monkeypatch):
    async def stream(_self, *_args, **_kwargs):
        for text, output in [("a", 10), ("b", 20)]:
            yield AIMessageChunk(content=text, usage_metadata={
                "input_tokens": 100, "output_tokens": output, "total_tokens": 100 + output,
            }, response_metadata={"token_usage": {"prompt_tokens": 100, "completion_tokens": output,
                                                   "prompt_cache_hit_tokens": 40}})

    monkeypatch.setattr(ReasoningChatOpenAI, "astream", stream)
    recorder = UsageRecorder()
    token = current_run_id.set("run_stream")
    try:
        assert "".join([text async for text in _llm(recorder).astream([{"role": "user", "content": "hello"}])]) == "ab"
    finally:
        current_run_id.reset(token)
    record = recorder.snapshot()[0]
    assert (record.input_tokens, record.output_tokens, record.total_tokens) == (100, 20, 120)
    assert record.cached_input_tokens == 40
    assert record.usage_complete


async def test_cancelled_stream_has_an_incomplete_usage_record(monkeypatch):
    async def stream(_self, *_args, **_kwargs):
        yield AIMessageChunk(content="started")
        yield AIMessageChunk(content="continued")

    monkeypatch.setattr(ReasoningChatOpenAI, "astream", stream)
    recorder = UsageRecorder()
    token = current_run_id.set("run_cancelled")
    try:
        gen = _llm(recorder).astream([{"role": "user", "content": "hello"}])
        assert await anext(gen) == "started"
        await gen.aclose()
    finally:
        current_run_id.reset(token)
    record = recorder.snapshot()[0]
    assert record.status == "cancelled"
    assert record.input_tokens is None and record.output_tokens is None
    assert not record.usage_complete
    assert record.usage_source == "missing"


async def test_each_sdk_attempt_is_a_separate_row_with_returned_error_usage(monkeypatch):
    import travel_agent.models.router as router_module

    attempts = []

    def respond(request):
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(503, json={"error": {"message": "retry", "type": "overloaded"},
                                            "usage": {"prompt_tokens": 10, "completion_tokens": 2}})
        return httpx.Response(200, json={"id": "chat_test", "object": "chat.completion", "created": 0,
            "model": "deepseek-v4.1-flash", "choices": [{"index": 0, "message": {
                "role": "assistant", "content": "done"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})

    recorder = UsageRecorder()
    token = current_run_id.set("run_attempts")
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            monkeypatch.setattr(router_module, "ChatOpenAI", lambda **kwargs: ReasoningChatOpenAI(
                **kwargs, http_async_client=client))
            llm = _llm(recorder)
            assert llm._client.max_retries == 0
            assert await llm.ainvoke([{"role": "user", "content": "hello"}]) == "done"
    finally:
        current_run_id.reset(token)
    first, second = recorder.snapshot()
    assert first.status == "error" and second.status == "ok"
    assert first.input_tokens == 10 and first.output_tokens == 2
    assert first.logical_call_id == second.logical_call_id
    assert (first.attempt_number, second.attempt_number) == (1, 2)
    summary = summarize_calls("run_attempts", [build_ledger_call(r, pricing=[]) for r in recorder.snapshot()])
    assert summary["call_count"] == 2 and summary["logical_call_count"] == 1
    assert summary["total_tokens"] == 132
