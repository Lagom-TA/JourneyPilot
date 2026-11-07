import pytest

from travel_agent.llm.task_routing import TaskKind, select_task_route

PRIMARY, FAST = "openai/gpt-6.1-sol", "deepseek/deepseek-v4.1-flash"


@pytest.mark.parametrize("task,tier,effort", [
    (TaskKind.QUICK_ANSWER, "fast", "low"),
    (TaskKind.PLANNING, "primary", "medium"), (TaskKind.COMPOSITION, "primary", "medium"),
])
def test_task_defaults_are_model_named_and_keep_reasoning_enabled(task, tier, effort):
    route = select_task_route(task, PRIMARY, FAST)
    assert route.tier == tier and route.reasoning_effort == effort


@pytest.mark.parametrize("primary", [PRIMARY, FAST])
def test_understanding_keeps_the_strong_model_with_tools(primary):
    """理解阶段带工具也保持 primary 档，不存在静默降档路径。"""

    route = select_task_route(TaskKind.UNDERSTANDING, primary, FAST, has_tools=True)
    assert route.tier == "primary"
    assert route.model_name == primary


def test_research_tools_stay_on_the_fast_tier():
    route = select_task_route(TaskKind.RESEARCH_TOOLS, PRIMARY, FAST, has_tools=True)
    assert route.tier == "fast" and route.model_name == FAST
