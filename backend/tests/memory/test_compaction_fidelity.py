import json
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


@pytest.mark.parametrize(
    ("question", "answer", "confirmed_constraint"),
    [
        ("这趟行程要避开夜行吗？", "不用，可以夜间出行。", "旅行者可以夜间出行"),
        ("对什么食物过敏？", "花生。", "旅行者对花生过敏"),
        ("这趟行程要避开夜行吗？", "还不确定。", None),
    ],
)
async def test_compaction_preserves_question_answer_sources_and_current_inputs(
    monkeypatch, question, answer, confirmed_constraint
):
    qa_message = f"用户回答：\n助手提问（q1）：{question}\n旅行者回答：{answer}"
    messages = [
        {"role": "user", "content": "去苏州三天，每晚住宿不超过500元。"},
        {"role": "user", "content": "本次已提交表单（含默认值）：同行2人。"},
        {"role": "assistant", "content": "可以考虑住在市中心。"},
        {"role": "user", "content": qa_message},
    ]
    expected_summary = f"去苏州三天。助手提问：{question}旅行者回答：{answer}"
    expected_constraints = ["每晚住宿不超过500元", "同行2人"]
    if confirmed_constraint:
        expected_constraints.append(confirmed_constraint)
    captured = []

    class LLM:
        async def ainvoke(self, prompt):
            captured.extend(prompt)
            return json.dumps({
                "summary": expected_summary,
                "key_constraints": expected_constraints,
            }, ensure_ascii=False)

    get_for_task = Mock(return_value=LLM())
    monkeypatch.setattr("travel_agent.llm.router.get_model_router", lambda: SimpleNamespace(get_for_task=get_for_task))
    result = await ContextCompressor().compress(messages, existing_anchor=anchor())

    get_for_task.assert_called_once_with(TaskKind.SUMMARY, has_tools=False)
    assert result.summary == expected_summary
    assert result.key_constraints == expected_constraints
    system_prompt = captured[0]["content"]
    assert "已提交表单中的值（包括默认值）和本次问答同等考虑" in system_prompt
    assert "结合完整的一问一答理解回答" in system_prompt
    assert "提问中涉及的条件以旅行者的回答判断是否确认" in system_prompt
    assert "问答成对保留" in system_prompt
    assert "早先消息里的用户约束也要保留" in system_prompt
    user_content = captured[1]["content"]
    assert f"用户：{qa_message}" in user_content
    assert "用户：本次已提交表单（含默认值）：同行2人。" in user_content
    assert "助手：可以考虑住在市中心。" in user_content
    assert "对话摘要中的约束（结合来源理解）：" in user_content
    assert "用户明确约束（必须严格遵守）" not in user_content


async def test_model_constraints_remain_an_attributed_summary_in_built_context():
    summary = AnchorSummary(
        "now", 2, 100, 20,
        ["需要避开夜行", "每晚住宿不超过500元"],
        "助手提问：需要避开夜行吗？旅行者回答：不用。",
    )
    result = await ContextBuilder().build_context("session", "contract", [], session_anchor=summary)

    assert "对话摘要中的约束（结合来源理解）：" in result.system_prompt
    assert "- 需要避开夜行" in result.system_prompt
    assert "- 每晚住宿不超过500元" in result.system_prompt
    assert "助手提问：需要避开夜行吗？旅行者回答：不用。" in result.system_prompt
    assert "用户明确约束（必须严格遵守）" not in result.system_prompt


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
