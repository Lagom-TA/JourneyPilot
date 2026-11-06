"""恢复被中断或失败的 Run：补回停下来的空档，并让停在已记录交付失败上的 Run 回到行程组合重跑。"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from travel_agent.planning.graph import build_travel_workflow
from travel_agent.planning.nodes import (
    NODE_DELIVERY_FINALIZER,
    NODE_DISPATCHER,
    NODE_ITINERARY,
)
from travel_agent.planning.outcomes import DeliveryFailureRecord, InternalFailureClass
from travel_agent.planning.workflow import TravelPlanningWorkflow
from travel_agent.runtime.budget import RunBudgetSnapshot
from travel_agent.runtime.deadlines import (
    RunDeadlineSnapshot,
    observe_run_deadline,
    renew_deadline_after_interruption,
    renew_deadline_for_composition_retry,
    utc_now,
)

T0 = datetime(2026, 11, 6, 0, 45, tzinfo=timezone.utc)


def _snapshot(*, last_observed_after: float = 100.0, elapsed: float = 100.0) -> RunDeadlineSnapshot:
    windows = {"target": 600, "closeout": 900, "composition": 1200, "delivery_deadline": 1500}
    return RunDeadlineSnapshot(
        draft_id="draft_resume",
        planning_authorized_at=T0,
        target_at=T0 + timedelta(seconds=windows["target"]),
        closeout_at=T0 + timedelta(seconds=windows["closeout"]),
        composition_at=T0 + timedelta(seconds=windows["composition"]),
        delivery_deadline_at=T0 + timedelta(seconds=windows["delivery_deadline"]),
        target_seconds=windows["target"],
        closeout_seconds=windows["closeout"],
        composition_seconds=windows["composition"],
        delivery_deadline_seconds=windows["delivery_deadline"],
        checkpointed_elapsed_seconds=elapsed,
        last_observed_at=T0 + timedelta(seconds=last_observed_after),
    )


def test_the_interruption_gap_is_added_to_every_window_and_stays_valid():
    snapshot = _snapshot()
    resumed_at = T0 + timedelta(hours=9)

    renewed = renew_deadline_after_interruption(snapshot, now=resumed_at)

    gap = 9 * 3600 - 100
    assert renewed is not None
    assert renewed.target_seconds == 600 + gap
    assert renewed.delivery_deadline_seconds == 1500 + gap
    assert renewed.delivery_deadline_at == snapshot.delivery_deadline_at + timedelta(seconds=gap)
    assert renewed.last_observed_at == resumed_at
    RunDeadlineSnapshot.model_validate(renewed.model_dump())


def test_a_run_resumed_long_after_the_interruption_is_not_expired_on_arrival():
    snapshot = _snapshot()
    resumed_at = T0 + timedelta(hours=9)

    _, stale = observe_run_deadline(snapshot, now=resumed_at, process_elapsed_seconds=0)
    renewed = renew_deadline_after_interruption(snapshot, now=resumed_at)
    _, fresh = observe_run_deadline(renewed, now=resumed_at + timedelta(seconds=1), process_elapsed_seconds=0)

    assert stale.phase == "expired"
    assert fresh.phase == "research"
    assert fresh.remaining_seconds > 1000


def test_the_budget_that_was_already_spent_before_the_interruption_stays_spent():
    snapshot = _snapshot(last_observed_after=1000, elapsed=1000)
    resumed_at = T0 + timedelta(hours=2)

    renewed = renew_deadline_after_interruption(snapshot, now=resumed_at)
    _, observation = observe_run_deadline(renewed, now=resumed_at + timedelta(seconds=1), process_elapsed_seconds=0)

    # 中断前已用 1000 秒（超过收口线 900），补回空档不会把它退回到“研究”阶段。
    assert observation.phase in {"closeout", "composition_closed"}
    assert 1000 + 1 > renewed.closeout_seconds - (2 * 3600 - 1000) - 1


def test_no_gap_means_nothing_to_renew():
    snapshot = _snapshot(last_observed_after=100)

    assert renew_deadline_after_interruption(snapshot, now=T0 + timedelta(seconds=100)) is None
    assert renew_deadline_after_interruption(snapshot, now=T0 + timedelta(seconds=50)) is None


def test_a_composition_retry_puts_the_run_back_at_its_target_point():
    # 已用时间早在失败前就被记成 3 小时（中断空档被算了进去），最后一次观测也很久以前。
    snapshot = _snapshot(last_observed_after=3 * 3600, elapsed=3 * 3600)
    now = utc_now()

    renewed = renew_deadline_for_composition_retry(snapshot, now=now)
    _, observation = observe_run_deadline(renewed, now=now + timedelta(seconds=1), process_elapsed_seconds=0)

    assert renewed.delivery_deadline_seconds - renewed.target_seconds == 1500 - 600
    assert observation.phase == "target_missed"
    assert observation.remaining_seconds > 800
    assert renewed.checkpointed_elapsed_seconds >= 3 * 3600
    RunDeadlineSnapshot.model_validate(renewed.model_dump())


def test_a_run_that_is_still_before_its_target_keeps_its_windows_on_retry():
    now = T0 + timedelta(seconds=200)
    snapshot = _snapshot(last_observed_after=100, elapsed=100)

    renewed = renew_deadline_for_composition_retry(snapshot, now=now)

    assert renewed.target_seconds == snapshot.target_seconds
    assert renewed.delivery_deadline_seconds == snapshot.delivery_deadline_seconds


def test_each_interruption_is_added_once():
    snapshot = _snapshot()
    first = renew_deadline_after_interruption(snapshot, now=T0 + timedelta(hours=1))
    second = renew_deadline_after_interruption(first, now=T0 + timedelta(hours=1, seconds=30))

    assert second.delivery_deadline_seconds == first.delivery_deadline_seconds + 30


class _Graph:
    def __init__(self, values, next_nodes=()):
        self.values = values
        self.next_nodes = next_nodes
        self.inputs = []
        self.updates = []

    async def aget_state(self, config):
        assert config == {"configurable": {"thread_id": "run_x"}}
        return SimpleNamespace(values=self.values, next=self.next_nodes)

    async def aupdate_state(self, config, values, *, as_node):
        self.updates.append((config, values, as_node))

    async def astream(self, graph_input, **kwargs):
        self.inputs.append(graph_input)
        if False:
            yield None


def _workflow(graph):
    workflow = object.__new__(TravelPlanningWorkflow)
    workflow._graph = graph
    workflow._checkpointer = None
    workflow._delivery_bundle_store = None
    workflow._trip_run_store = None
    return workflow


async def _drain(workflow, **kwargs):
    return [item async for item in workflow.astream("继续", "session", run_id="run_x", resume_from_checkpoint=True, **kwargs)]


def _failure() -> DeliveryFailureRecord:
    return DeliveryFailureRecord(
        failure_class=InternalFailureClass.UNCLASSIFIED,
        operation=NODE_ITINERARY,
        attempts=1,
        retry_exhausted=True,
        public_message="行程组合失败，请稍后重试。",
    )


@pytest.mark.asyncio
async def test_resuming_an_interrupted_run_continues_with_the_renewed_deadline():
    snapshot = _snapshot(last_observed_after=100)
    graph = _Graph({"run_deadline": snapshot})

    await _drain(_workflow(graph))

    (graph_input,) = graph.inputs
    assert isinstance(graph_input, Command)
    renewed = graph_input.update["run_deadline"]
    assert renewed.delivery_deadline_seconds > snapshot.delivery_deadline_seconds
    assert renewed.last_observed_at > snapshot.last_observed_at
    assert graph.updates == []


@pytest.mark.asyncio
async def test_a_checkpoint_without_a_deadline_resumes_unchanged():
    graph = _Graph({})

    await _drain(_workflow(graph))

    assert graph.inputs == [None]


@pytest.mark.asyncio
async def test_a_gate_decision_resume_is_left_to_the_gate():
    graph = _Graph({"run_deadline": _snapshot()}, (NODE_DELIVERY_FINALIZER,))

    await _drain(_workflow(graph), resume_payload={"action": "retry"})

    (graph_input,) = graph.inputs
    assert isinstance(graph_input, Command) and graph_input.resume == {"action": "retry"}
    assert graph_input.update is None
    assert graph.updates == []


@pytest.mark.asyncio
async def test_a_run_parked_on_a_recorded_delivery_failure_goes_back_to_composition():
    values = {
        "run_deadline": _snapshot(),
        "delivery_failure": _failure(),
        "agent_assignments": {NODE_ITINERARY: {"objective": "组合行程"}},
    }
    graph = _Graph(values, (NODE_DELIVERY_FINALIZER,))

    await _drain(_workflow(graph))

    ((config, update, as_node),) = graph.updates
    assert config == {"configurable": {"thread_id": "run_x"}}
    assert as_node == NODE_ITINERARY
    assert update["delivery_failure"] is None
    assert update["agent_status"] == {NODE_ITINERARY: "pending"}
    assert update["run_deadline"].delivery_deadline_seconds > 1500
    assert update["run_deadline"].delivery_deadline_seconds - update["run_deadline"].target_seconds == 900
    assert graph.inputs == [None]


@pytest.mark.asyncio
async def test_a_failure_record_the_finalizer_is_not_waiting_on_is_left_alone():
    graph = _Graph(
        {"delivery_failure": _failure(), "agent_assignments": {NODE_ITINERARY: {"objective": "组合行程"}}},
        (NODE_DISPATCHER,),
    )

    await _drain(_workflow(graph))

    assert graph.updates == []
    assert graph.inputs == [None]


@pytest.mark.asyncio
async def test_without_a_composition_assignment_only_the_deadline_is_renewed():
    graph = _Graph(
        {"run_deadline": _snapshot(), "delivery_failure": _failure()}, (NODE_DELIVERY_FINALIZER,)
    )

    await _drain(_workflow(graph))

    assert graph.updates == []
    (graph_input,) = graph.inputs
    assert isinstance(graph_input, Command) and "run_deadline" in graph_input.update


@pytest.mark.asyncio
async def test_the_real_graph_leaves_the_rewound_run_waiting_at_the_dispatcher():
    graph = build_travel_workflow().compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "run_x"}}
    await graph.aupdate_state(
        config,
        {
            "run_id": "run_x",
            "session_id": "session",
            "user_query": "调整第二天晚餐",
            "run_deadline": _snapshot(),
            "run_budget": RunBudgetSnapshot(),
            "agent_assignments": {NODE_ITINERARY: {"objective": "组合行程"}},
            "agent_status": {NODE_ITINERARY: "failed"},
            "delivery_failure": _failure(),
            "composition_failure_context": "上一轮路线耗时超出窗口",
        },
        as_node=NODE_DISPATCHER,
    )
    parked = await graph.aget_state(config)
    assert parked.next == (NODE_DELIVERY_FINALIZER,)

    assert await _workflow(graph)._resume_graph_input("run_x") is None

    resumed = await graph.aget_state(config)
    assert resumed.next == (NODE_DISPATCHER,)
    assert resumed.values["delivery_failure"] is None
    assert resumed.values["agent_status"][NODE_ITINERARY] == "pending"
    assert resumed.values["composition_failure_context"] == "上一轮路线耗时超出窗口"
    _, observation = observe_run_deadline(resumed.values["run_deadline"])
    assert observation.phase in {"research", "target_missed"}
    assert observation.remaining_seconds > 800
