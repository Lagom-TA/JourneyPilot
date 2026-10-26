from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from travel_agent.llm.task_routing import TaskKind, llm_for_task, select_task_route

PRIMARY, FAST = "openai/gpt-6.1-sol", "deepseek/deepseek-v4.1-flash"


@pytest.mark.parametrize("task,tier,effort", [
    (TaskKind.RESEARCH_TOOLS, "fast", "low"), (TaskKind.QUICK_ANSWER, "fast", "low"),
    (TaskKind.SUMMARY, "fast", "low"), (TaskKind.INTENT_NORMALIZE, "fast", "low"),
    (TaskKind.COMPOSITION, "primary", "medium"),
    (TaskKind.CONSTRAINT_ARBITRATION, "primary", "medium"),
])
def test_task_defaults_are_model_named_and_keep_reasoning_enabled(task, tier, effort):
    route = select_task_route(task, PRIMARY, FAST)
    assert route.tier == tier and route.reasoning_effort == effort


def test_llm_for_task_forwards_tool_capability():
    get_for_task = Mock(return_value=object())
    router = SimpleNamespace(get_for_task=get_for_task)

    assert llm_for_task(router, TaskKind.RESEARCH_TOOLS, has_tools=True) is get_for_task.return_value
    get_for_task.assert_called_once_with(TaskKind.RESEARCH_TOOLS, has_tools=True)


def test_tool_research_never_silently_switches_to_sol_chat_tools():
    route = select_task_route(TaskKind.RESEARCH_TOOLS, PRIMARY, FAST, has_tools=True)
    assert route.tier == "fast"
    with pytest.raises(ValueError, match="Responses"):
        select_task_route(TaskKind.RESEARCH_TOOLS, PRIMARY, PRIMARY, has_tools=True)
