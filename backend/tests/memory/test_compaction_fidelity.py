from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from travel_agent.llm.task_routing import TaskKind
from travel_agent.memory.compressor import AnchorSummary, ContextCompressor
from travel_agent.memory.context_builder import ContextBudget, ContextBuilder


def anchor():
    return AnchorSummary("now", 2, 100, 20, ["不能爬楼", "每晚预算不超过500元"], "去杭州")


async def test_compaction_uses_model_key_constraints_as_is(monkeypatch):
    class LLM:
        async def ainvoke(self, messages):
            return '{"summary":"杭州旅行，预算300元", "key_constraints":["必须住五星酒店", "每晚预算不超过300元", 3]}'
    get_for_task = Mock(return_value=LLM())
    monkeypatch.setattr("travel_agent.llm.router.get_model_router", lambda: SimpleNamespace(get_for_task=get_for_task))
    result = await ContextCompressor().compress([
        {"role": "user", "content": "每晚预算不超过300元"},
        {"role": "assistant", "content": "必须住五星酒店"},
    ], existing_anchor=anchor())
    get_for_task.assert_called_once_with(TaskKind.SUMMARY, has_tools=False)
    assert result.key_constraints == ["必须住五星酒店", "每晚预算不超过300元"]


@pytest.mark.parametrize("output", ['[]', 'null', '{"summary":42}', 'broken'])
async def test_invalid_summary_never_advances_compaction_by_degraded_excerpt(monkeypatch, output):
    class LLM:
        async def ainvoke(self, messages):
            return output
    get_for_task = Mock(return_value=LLM())
    monkeypatch.setattr("travel_agent.llm.router.get_model_router", lambda: SimpleNamespace(get_for_task=get_for_task))
    with pytest.raises(ValueError):
        await ContextCompressor().compress([{"role": "user", "content": "后面的约束不能丢"}])
    get_for_task.assert_called_once_with(TaskKind.SUMMARY, has_tools=False)


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
