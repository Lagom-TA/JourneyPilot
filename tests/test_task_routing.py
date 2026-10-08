from copy import deepcopy
from types import SimpleNamespace

import pytest

from travel_agent.models.task_routing import QualityFeedback, TaskKind, TaskLLM, select_task_route

PRIMARY, FAST = "openai/gpt-6.1-sol", "deepseek/deepseek-v4.1-flash"


@pytest.mark.parametrize("task,tier,effort", [
    (TaskKind.RESEARCH_TOOLS, "fast", "low"), (TaskKind.QUICK_ANSWER, "fast", "low"),
    (TaskKind.SUMMARY, "fast", "low"), (TaskKind.INTENT_NORMALIZE, "fast", "low"),
    (TaskKind.CANDIDATE_EVALUATION, "fast", "low"), (TaskKind.COMPOSITION, "primary", "medium"),
    (TaskKind.CONSTRAINT_ARBITRATION, "primary", "medium"),
])
def test_task_defaults_are_model_named_and_keep_reasoning_enabled(task, tier, effort):
    route = select_task_route(task, PRIMARY, FAST)
    assert route.tier == tier and route.reasoning_effort == effort


def test_evidence_gap_requests_research_without_model_upgrade():
    route = select_task_route(TaskKind.CANDIDATE_EVALUATION, PRIMARY, FAST,
                              QualityFeedback(hard_gate_unknown=True, evidence_available=False))
    assert route.tier == "fast" and route.action == "research_required"


@pytest.mark.parametrize("feedback", [QualityFeedback(schema_failures=1), QualityFeedback(truncated=True), QualityFeedback(hard_gate_failed=True)])
def test_quality_failures_upgrade_schema_only_tasks(feedback):
    route = select_task_route(TaskKind.SCHEMA_REPAIR, PRIMARY, FAST, feedback)
    assert route.tier == "primary" and route.reason == "quality_failure"


def test_tool_research_never_silently_switches_to_sol_chat_tools():
    route = select_task_route(TaskKind.RESEARCH_TOOLS, PRIMARY, FAST, QualityFeedback(schema_failures=3), has_tools=True)
    assert route.tier == "fast"
    with pytest.raises(ValueError, match="Responses"):
        select_task_route(TaskKind.RESEARCH_TOOLS, PRIMARY, PRIMARY, has_tools=True)


async def test_sol_repair_preserves_evidence_as_observations_without_foreign_reasoning():
    captured = []
    class Client:
        async def ainvoke(self, messages, **kwargs):
            captured.append(messages)
            return "ok"
    route = select_task_route(TaskKind.SCHEMA_REPAIR, PRIMARY, FAST, QualityFeedback(schema_failures=1))
    llm = TaskLLM(SimpleNamespace(), route, Client())
    messages = [
        {"role": "system", "content": "fixed contract"},
        {"role": "assistant", "content": "", "tool_calls": [{"name": "read", "id": "a", "arguments": {}}],
         "assistant_replay": {"reasoning_content": "foreign"}},
        {"role": "tool", "tool_call_id": "a", "content": '{"audit_id":"authoritative","value":42}'},
    ]
    before = deepcopy(messages)
    await llm.ainvoke(messages)
    assert messages == before
    assert all(m["role"] != "tool" and "tool_calls" not in m and "assistant_replay" not in m for m in captured[0])
    assert "authoritative" in captured[0][-1]["content"] and "42" in captured[0][-1]["content"]
    with pytest.raises(ValueError, match="Responses"):
        async for _ in llm.astream_with_tools(messages, []):
            pass


async def test_candidate_schema_failure_uses_primary_repair_with_same_evidence():
    from travel_agent.services.candidate_intent_evaluation import _semantic_batch_call
    requests = []
    class Client:
        def __init__(self, tier):
            self.tier = tier
        async def ainvoke(self, messages, **kwargs):
            requests.append((self.tier, deepcopy(messages)))
            return 'broken' if self.tier == "fast" else '{"matches":[]}'
    class Router:
        def get_for_task(self, task, feedback=None, **kwargs):
            route = select_task_route(task, PRIMARY, FAST, feedback)
            return TaskLLM(self, route, Client(route.tier))
    llm = Router().get_for_task(TaskKind.CANDIDATE_EVALUATION)
    evidence = [{"role": "user", "content": "facts from source_1, value=42"}]
    assert await _semantic_batch_call(llm, evidence) == '{"matches":[]}'
    assert [tier for tier, _ in requests] == ["fast", "primary"]
    assert requests[0][1] == requests[1][1] == evidence
