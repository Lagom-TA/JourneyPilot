"""运行图节点应具有供界面展示的元数据。"""

from functools import lru_cache

import pytest


@lru_cache(maxsize=1)
def _travel_graph():
    from travel_agent.planning.graph import build_travel_workflow

    return build_travel_workflow()


@lru_cache(maxsize=1)
def _graph_node_names() -> frozenset[str]:
    from travel_agent.conversation.graph import NODE_FAST_ANSWER

    return frozenset(_travel_graph().nodes) | {NODE_FAST_ANSWER}


@pytest.mark.parametrize(
    ("table_name", "extra_keys"),
    [
        ("trace", {"workflow"}),
        ("agent", set()),
        (
            "step",
            {"planning", "researching", "synthesizing"},
        ),
    ],
)
def test_user_facing_node_metadata_matches_the_runtime_graph(table_name, extra_keys):
    from travel_agent.planning.presentation import (
        AGENT_DISPLAY_NAMES,
        STEP_DISPLAY_NAMES,
    )
    from travel_agent.planning.trace import NODE_PHASES

    tables = {
        "trace": NODE_PHASES,
        "agent": AGENT_DISPLAY_NAMES,
        "step": STEP_DISPLAY_NAMES,
    }
    assert set(tables[table_name]) == set(_graph_node_names()) | extra_keys
