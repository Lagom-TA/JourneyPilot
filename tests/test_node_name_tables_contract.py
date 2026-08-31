"""Behavioral coverage for graph metadata that directly drives UI and resume routing."""

from functools import lru_cache

import pytest


@lru_cache(maxsize=1)
def _travel_graph():
    from travel_agent.workflows.travel_planning import build_travel_workflow

    return build_travel_workflow()


@lru_cache(maxsize=1)
def _graph_node_names() -> frozenset[str]:
    from travel_agent.workflows.fast_answer import NODE_FAST_ANSWER

    return frozenset(_travel_graph().nodes) | {NODE_FAST_ANSWER}


@pytest.mark.parametrize(
    ("table_name", "extra_keys"),
    [
        ("trace", {"workflow"}),
        ("agent", {"supervisor"}),
        (
            "step",
            {"supervisor", "orchestrating", "planning", "researching", "synthesizing"},
        ),
    ],
)
def test_user_facing_node_metadata_matches_the_runtime_graph(table_name, extra_keys):
    from travel_agent.utils.display_names import (
        AGENT_DISPLAY_NAMES,
        STEP_DISPLAY_NAMES,
    )
    from travel_agent.workflows.trace import NODE_PHASES

    tables = {
        "trace": NODE_PHASES,
        "agent": AGENT_DISPLAY_NAMES,
        "step": STEP_DISPLAY_NAMES,
    }
    assert set(tables[table_name]) == set(_graph_node_names()) | extra_keys


def test_intent_amendments_can_resume_at_every_runtime_node_that_accepts_them():
    graph = _travel_graph()
    branch = (graph.branches.get("intent_amendment_router") or {}).get(
        "route_after_intent_amendment"
    )
    assert branch is not None and branch.ends

    non_resumable = {"scope_clarifier", "intent_amendment_router"}
    assert set(branch.ends) == set(graph.nodes) - non_resumable
