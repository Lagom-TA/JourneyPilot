"""补充要求的续跑目标必须落在图的条件边表内。

`intent_amendment_router` 的图分支表与运行时 divert 守卫都来自
`AMENDMENT_CONTINUATION_NODES`；本文件同时守住生产者（apply_runtime_amendments）
不会输出表外目标。
"""

from __future__ import annotations

import pytest

from travel_agent.planning.execution import _should_divert_to_amendment_router
from travel_agent.planning.graph import build_travel_workflow
from travel_agent.planning.nodes import AMENDMENT_CONTINUATION_NODES
from travel_agent.planning.requirements.amendment_contracts import IntentAmendment
from travel_agent.planning.requirements.amendments import apply_runtime_amendments
from travel_agent.planning.requirements.generation_contracts import PlanningGeneration
from travel_agent.planning.state import TravelAgentState

_NON_RESUMABLE = {"scope_clarifier", "understanding_gate", "intent_amendment_router"}


def _amendment(content: str = "多安排一天", command_id: str = "cmd-1") -> IntentAmendment:
    return IntentAmendment(
        command_id=command_id,
        category="other",
        content=content,
        source_kind="run_supplement",
    )


def _state(
    *,
    amendments: list[IntentAmendment] | None = None,
    resume_node: str | None = None,
) -> TravelAgentState:
    return TravelAgentState(
        run_id="run-amendment-routing",
        planning_generation=PlanningGeneration(generation_id="generation-1", revision=1),
        pending_intent_amendments=amendments or [],
        intent_amendment_resume_node=resume_node,
    )


def _branch_ends() -> set[str]:
    graph = build_travel_workflow()
    branch = (graph.branches.get("intent_amendment_router") or {}).get(
        "route_after_intent_amendment"
    )
    assert branch is not None and branch.ends
    return set(branch.ends)


def test_continuation_table_equals_graph_branch_targets() -> None:
    graph = build_travel_workflow()
    assert _branch_ends() == set(AMENDMENT_CONTINUATION_NODES)
    assert set(AMENDMENT_CONTINUATION_NODES) == set(graph.nodes) - _NON_RESUMABLE


@pytest.mark.parametrize(
    "node_name", ["understanding_agent", "dispatcher", "delivery_finalizer"]
)
def test_continuation_nodes_route_inside_the_table(node_name: str) -> None:
    """接受与拒绝两条分支都只能落到续跑表内的节点。"""

    accepted = apply_runtime_amendments(
        _state(amendments=[_amendment()], resume_node=node_name)
    )
    assert accepted["intent_amendment_route"] in set(AMENDMENT_CONTINUATION_NODES)

    rejected = apply_runtime_amendments(
        _state(
            amendments=[_amendment(content="帮我付款订好酒店")],
            resume_node=node_name,
        )
    )
    assert rejected["intent_amendment_route"] == node_name


@pytest.mark.parametrize("node_name", sorted(_NON_RESUMABLE))
def test_non_resumable_nodes_never_start_an_amendment_detour(node_name: str) -> None:
    """入口整理、提问暂停点与路由器自身不能被 supplement 打断。"""

    assert not _should_divert_to_amendment_router(
        fresh_amendments=[_amendment()],
        state=_state(),
        node_name=node_name,
    )


def test_handled_nodes_keep_their_own_boundary() -> None:
    """需求整理与计划门在节点内处理追加要求，不在这里 divert。"""

    for node_name in ("requirements_preparer", "plan_gate"):
        assert not _should_divert_to_amendment_router(
            fresh_amendments=[_amendment()],
            state=_state(),
            node_name=node_name,
        )


@pytest.mark.parametrize("resume_node", ["scope_clarifier", "ghost_node"])
def test_router_rejects_a_resume_target_outside_the_table(resume_node: str) -> None:
    """状态里带着表外续跑目标时，路由层直接拒绝，而不是交给 LangGraph 报错。"""

    with pytest.raises(ValueError, match="outside continuation table"):
        apply_runtime_amendments(
            _state(
                amendments=[_amendment(content="帮我付款订好酒店")],
                resume_node=resume_node,
            )
        )
