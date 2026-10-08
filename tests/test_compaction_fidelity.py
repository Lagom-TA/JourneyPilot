from types import SimpleNamespace

import pytest

from travel_agent.memory.compressor import AnchorSummary, ContextCompressor, _merge_user_constraints
from travel_agent.memory.context_builder import ContextBudget, ContextBuilder


def anchor():
    return AnchorSummary("now", 2, 100, 20, ["不能爬楼", "每晚预算不超过500元"], "去杭州")


async def test_compaction_keeps_prior_constraints_and_rejects_assistant_inventions(monkeypatch):
    class LLM:
        async def ainvoke(self, messages):
            return '{"summary":"杭州旅行，预算300元", "key_constraints":["必须住五星酒店", "每晚预算不超过300元", 3]}'
    monkeypatch.setattr("travel_agent.models.router.get_model_router", lambda: SimpleNamespace(get_fast=lambda: LLM()))
    result = await ContextCompressor().compress([
        {"role": "user", "content": "每晚预算不超过300元"},
        {"role": "assistant", "content": "必须住五星酒店"},
    ], existing_anchor=anchor())
    assert "不能爬楼" in result.key_constraints
    assert "每晚预算不超过500元" in result.key_constraints
    assert "每晚预算不超过300元" in result.key_constraints
    assert "必须住五星酒店" not in result.key_constraints


@pytest.mark.parametrize("output", ['[]', 'null', '{"summary":42}', 'broken'])
async def test_invalid_summary_never_advances_compaction_by_degraded_excerpt(monkeypatch, output):
    class LLM:
        async def ainvoke(self, messages):
            return output
    monkeypatch.setattr("travel_agent.models.router.get_model_router", lambda: SimpleNamespace(get_fast=lambda: LLM()))
    with pytest.raises(ValueError):
        await ContextCompressor().compress([{"role": "user", "content": "后面的约束不能丢"}])


def test_more_specific_constraint_is_not_removed_as_substring():
    assert _merge_user_constraints(["不要爬楼"], ["不要爬楼，老人膝盖有伤"]) == ["不要爬楼", "不要爬楼，老人膝盖有伤"]


async def test_anchor_constraints_are_never_character_trimmed():
    summary = anchor()
    summary.summary = "old " * 3000
    builder = ContextBuilder(ContextBudget(total_context_limit=20000, response_reserve=100, anchor_summary_budget=5))
    result = await builder.build_context("session", "contract", [], session_anchor=summary)
    assert "不能爬楼" in result.system_prompt and "每晚预算不超过500元" in result.system_prompt


def test_history_trimming_keeps_tool_pairs_as_one_turn():
    builder = ContextBuilder()
    history = [
        {"role": "user", "content": "old" * 100},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "a", "name": "read", "arguments": {}}]},
        {"role": "tool", "tool_call_id": "a", "content": "result"},
        {"role": "user", "content": "latest"},
    ]
    assert builder._trim_messages(history, 20, "test") == history[-1:]


async def test_next_request_window_includes_runtime_rag_and_output_reserve():
    builder = ContextBuilder(ContextBudget(total_context_limit=100, response_reserve=30, compaction_threshold=0.5))
    result = await builder.build_context("session", "contract", [{"role": "user", "content": "history" * 15}],
                                         runtime_messages=[{"role": "user", "content": "facts" * 30}])
    assert result.needs_compaction
    assert result.token_usage["runtime"] > 0
    assert result.token_usage["total_estimated"] + 30 <= 100
