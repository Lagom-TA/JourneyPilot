"""交付收口：组合失败或截止窗口关闭时按当前结果选择定稿或投影。"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import MemorySaver

from tests.fixtures.itinerary import itinerary_draft, visit_entry
from tests.fixtures.research_catalog import make_visit_packet
from tests.support.memory_stores import InMemoryDeliveryBundleStore
from tests.support.memory_stores import InMemoryTripRunStore
from travel_agent.planning.delivery.completion import DeliveryFinalizationError
from travel_agent.planning.delivery.finalizer import delivery_finalizer_node
from travel_agent.planning.delivery.projection_node import delivery_projection_node
from travel_agent.planning.delivery.minimum_draft import (
    build_minimum_delivery_draft,
    seal_minimum_delivery_draft,
)
from travel_agent.planning.itinerary.draft import ItineraryCompositionDraft
from travel_agent.planning.itinerary.materialize import materialize_trip_workspace
from travel_agent.planning.graph import build_travel_workflow
from travel_agent.planning.nodes import (
    NODE_DELIVERY_FINALIZER,
    NODE_DELIVERY_PROJECTOR,
    NODE_DISPATCHER,
    NODE_ITINERARY,
)
from travel_agent.planning.outcomes import InternalFailureClass
from travel_agent.planning.requirements.generation_contracts import PlanningGeneration
from travel_agent.planning.research import dispatch
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.weather.models import WeatherContextSnapshot
from travel_agent.runtime.deadlines import DeadlineObservation
from travel_agent.runtime.run_contracts import TripRunStatus
from travel_agent.tools.result import ReactOutcome, ReactResult


def _identity() -> dict:
    place = {
        "place_id": "destination_tokyo",
        "provider": "osm",
        "kind": "city",
        "name": "东京",
        "display_name": "东京",
        "country_code": "JP",
        "latitude": 35.68,
        "longitude": 139.76,
        "admin_path": [],
    }
    return {
        "origin": place,
        "destinations": [place],
        "start_date": "2026-11-05",
        "end_date": "2026-11-05",
        "party": {
            "adults": 1,
            "children": 0,
            "elderly_companions": False,
            "accessibility_required": False,
        },
        "style": {"primary": "慢游", "secondary_interests": [], "source": "current"},
    }


def _workspace(run_id: str):
    from travel_agent.planning.requirements.inputs import UserInputAnchor
    from travel_agent.planning.requirements.place_names import (
        CONTROLLED_DESTINATION_ANCHOR_PREFIX,
    )

    generation_id = "generation_deadline"
    packet = make_visit_packet("candidate_visit", "原有景点").model_copy(
        update={
            "run_id": run_id,
            "generation_id": generation_id,
            "fact_data_revision": 0,
        }
    )
    catalog = RecommendationCatalog(
        generation_id=generation_id,
        fact_data_revision=0,
        weather_data_revision=0,
        research_packets=[packet],
    )
    draft = ItineraryCompositionDraft.model_validate(itinerary_draft([visit_entry()]))
    return materialize_trip_workspace(
        run_id=run_id,
        workspace_revision=0,
        composition=draft,
        catalog=catalog,
        requirements="喜欢安静的文化景点",
        composition_mutations=[],
        user_input_anchors=[
            UserInputAnchor(
                anchor_id="destination",
                field_path=(
                    f"{CONTROLLED_DESTINATION_ANCHOR_PREFIX}destination_tokyo"
                ),
                value=_identity()["destinations"][0],
                input_kind="controlled_identity",
            )
        ],
    )


def _weather(workspace) -> WeatherContextSnapshot:
    return WeatherContextSnapshot(
        weather_data_revision=0,
        trip_start_date=workspace.itinerary.day_plans[0].date,
        trip_end_date=workspace.itinerary.day_plans[-1].date,
        days=[],
        retrieved_at=datetime.now(timezone.utc),
    )


async def _running_run(runs: InMemoryTripRunStore) -> str:
    run = await runs.create_run(session_id="closeout-session", user_id="local", mode="deep")
    await runs.transition_status(run.run_id, TripRunStatus.RUNNING)
    return run.run_id


def _observation(phase: str) -> DeadlineObservation:
    return DeadlineObservation(elapsed_seconds=60.0, remaining_seconds=0.0, phase=phase)


def _sealed_state(run_id: str) -> TravelAgentState:
    state = TravelAgentState(
        run_id=run_id,
        planning_generation=PlanningGeneration(generation_id="generation_deadline", revision=1),
        controlled_trip_identity=_identity(),
    )
    draft = build_minimum_delivery_draft(state)
    assert draft is not None
    state = state.model_copy(update={"minimum_delivery_draft": draft})
    return state.model_copy(update=seal_minimum_delivery_draft(state))


@pytest.fixture
def deadline_observation(monkeypatch):
    def _install(phase: str) -> None:
        monkeypatch.setattr(
            dispatch,
            "observe_run_deadline",
            lambda deadline: (deadline, _observation(phase)),
        )

    return _install


def _failed_composition_state(run_id: str) -> TravelAgentState:
    return _sealed_state(run_id).model_copy(
        update={
            "execution_plan": [["destination_researcher"], ["itinerary_planner"]],
            "current_plan_step": 1,
            "agent_status": {
                "destination_researcher": "completed",
                "itinerary_planner": "failed",
            },
            "last_error": "route duration missing",
            "composition_failure_context": (
                "materialize_connectors 阶段失败 — ValueError: route duration missing"
            ),
        }
    )


@pytest.mark.parametrize(
    "phase", ["research", "target_missed", "closeout", "composition_closed", "expired"]
)
async def test_failed_composition_without_workspace_routes_to_finalizer(
    phase, deadline_observation, caplog
) -> None:
    state = _failed_composition_state("run_composition_failure")
    deadline_observation(phase)

    update = await dispatch.dispatcher_node(state)
    record = update["delivery_failure"]
    assert record.failure_class.value == "unclassified"
    assert record.operation == "itinerary_planner"
    assert record.attempts == 1 and record.retry_exhausted is True
    assert "route duration missing" not in record.public_message
    assert update["run_deadline"] == state.run_deadline

    state = state.model_copy(update=update)
    assert dispatch.route_after_dispatcher(state) == NODE_DELIVERY_FINALIZER
    assert state.last_error == "route duration missing"
    assert "materialize_connectors" in state.composition_failure_context
    assert state.run_id in caplog.text
    assert state.composition_failure_context in caplog.text
    assert state.last_error in caplog.text


@pytest.mark.parametrize("phase", ["research", "target_missed", "closeout"])
async def test_failed_research_waits_for_user_retry_before_composition(
    phase, deadline_observation
) -> None:
    state = _failed_composition_state("run_pending_composition").model_copy(
        update={
            "agent_assignments": {"destination_researcher": {"objective": "研究目的地"}},
            "agent_status": {
                "destination_researcher": "failed",
                "itinerary_planner": "pending",
            },
            "composition_failure_context": None,
        }
    )
    deadline_observation(phase)

    update = await dispatch.dispatcher_node(state)
    assert "delivery_failure" not in update
    assert update["research_failed_workers"] == ["destination_researcher"]
    assert dispatch.route_after_dispatcher(state.model_copy(update=update)) == "research_gate"


@pytest.mark.parametrize("phase", ["research", "closeout"])
async def test_failed_composition_with_workspace_keeps_existing_projection_route(
    phase, deadline_observation
) -> None:
    run_id = "run_existing_workspace"
    state = _failed_composition_state(run_id).model_copy(
        update={"trip_workspace": _workspace(run_id)}
    )
    deadline_observation(phase)

    update = await dispatch.dispatcher_node(state)
    assert "delivery_failure" not in update
    assert dispatch.route_after_dispatcher(state.model_copy(update=update)) == "to_check"


async def test_failed_composition_is_finalized_by_the_workflow(monkeypatch) -> None:
    monkeypatch.setattr(
        "travel_agent.planning.execution.ensure_budget_baseline", AsyncMock()
    )
    runs = InMemoryTripRunStore()
    bundles = InMemoryDeliveryBundleStore()
    run_id = await _running_run(runs)
    state = _failed_composition_state(run_id)
    config = {
        "configurable": {
            "thread_id": run_id,
            "trip_run_store": runs,
            "delivery_bundle_store": bundles,
        }
    }
    graph = build_travel_workflow().compile(checkpointer=MemorySaver())
    values = {name: getattr(state, name) for name in type(state).model_fields}
    await graph.aupdate_state(config, values, as_node=NODE_ITINERARY)
    assert (await graph.aget_state(config)).next == (NODE_DISPATCHER,)

    with pytest.raises(DeliveryFinalizationError) as exc_info:
        await graph.ainvoke(None, config)

    assert exc_info.value.record.operation == "itinerary_planner"
    assert str(exc_info.value.__cause__) == state.composition_failure_context
    checkpoint = await graph.aget_state(config)
    assert checkpoint.values["last_error"] == state.last_error
    assert checkpoint.values["composition_failure_context"] == state.composition_failure_context
    assert checkpoint.values["delivery_failure"].operation == "itinerary_planner"
    stored = await runs.get_run(run_id)
    assert stored is not None and stored.status is TripRunStatus.FAILED
    assert stored.last_error_code == "unclassified"
    assert "route duration missing" not in stored.last_error_message
    assert runs.events[run_id][-1].event_type == "run.delivery_failed"
    assert runs.events[run_id][-1].payload["operation"] == "itinerary_planner"
    assert await bundles.get_current(run_id) is None


@pytest.mark.parametrize(
    ("outcome", "error"),
    [
        (ReactOutcome.MODEL_FAILED, "APITimeoutError: upstream model timed out"),
        (ReactOutcome.BUDGET_LIMIT, "run budget exhausted on llm_calls"),
        (ReactOutcome.ITERATION_LIMIT, None),
    ],
)
async def test_react_failure_keeps_diagnostics_through_finalizer(
    monkeypatch, deadline_observation, outcome, error
) -> None:
    from travel_agent.planning.itinerary import composition, node

    runs = InMemoryTripRunStore()
    run_id = await _running_run(runs)
    state = _sealed_state(run_id).model_copy(
        update={
            "execution_plan": [["itinerary_planner"]],
            "agent_assignments": {"itinerary_planner": {"objective": "安排行程"}},
            "agent_status": {"itinerary_planner": "pending"},
            "recommendation_catalog": RecommendationCatalog(
                generation_id="generation_deadline",
                fact_data_revision=0,
                weather_data_revision=0,
                research_packets=[],
            ),
        }
    )
    monkeypatch.setattr(node, "get_available_tools", AsyncMock(return_value=[]))
    monkeypatch.setattr(node, "filter_tools_for_agent", lambda tools, _: tools)
    monkeypatch.setattr(node, "get_model_router", lambda: None)
    monkeypatch.setattr(node, "llm_for_task", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        composition,
        "streaming_react_loop",
        AsyncMock(return_value=ReactResult(outcome=outcome, error=error)),
    )

    state = state.model_copy(update=await node.itinerary_planner_node(state, {}))
    expected = f"composition tool loop ended without a final answer: {outcome.value}"
    if error:
        expected += f": {error}"
    assert state.last_error == expected
    assert state.agent_status["itinerary_planner"] == "failed"
    assert state.trip_workspace is None

    deadline_observation("research")
    state = state.model_copy(update=await dispatch.dispatcher_node(state))
    assert dispatch.route_after_dispatcher(state) == NODE_DELIVERY_FINALIZER
    assert state.delivery_failure.failure_class.value == "unclassified"
    assert state.delivery_failure.operation == "itinerary_planner"
    assert expected not in state.delivery_failure.public_message

    bundles = InMemoryDeliveryBundleStore()
    config = {"configurable": {"trip_run_store": runs, "delivery_bundle_store": bundles}}
    with pytest.raises(DeliveryFinalizationError) as exc_info:
        await delivery_finalizer_node(state, config)
    assert expected in str(exc_info.value.__cause__)
    assert runs.events[run_id][-1].payload["failure_class"] == "unclassified"
    assert await bundles.get_current(run_id) is None


@pytest.mark.parametrize(
    ("last_error", "expected_cause"),
    [
        ("delivery deadline elapsed before itinerary composition", "delivery deadline elapsed before itinerary composition"),
        (None, "itinerary_planner"),
    ],
)
async def test_composition_failure_cause_without_context(
    deadline_observation, last_error, expected_cause
) -> None:
    runs = InMemoryTripRunStore()
    run_id = await _running_run(runs)
    state = _failed_composition_state(run_id).model_copy(
        update={"composition_failure_context": None, "last_error": last_error}
    )
    deadline_observation("expired")
    state = state.model_copy(update=await dispatch.dispatcher_node(state))
    config = {
        "configurable": {
            "trip_run_store": runs,
            "delivery_bundle_store": InMemoryDeliveryBundleStore(),
        }
    }

    with pytest.raises(DeliveryFinalizationError) as exc_info:
        await delivery_finalizer_node(state, config)
    assert str(exc_info.value.__cause__) == expected_cause


async def test_closeout_without_workspace_marks_the_run_failed(
    deadline_observation,
) -> None:
    """没有 workspace 时不进 projector：dispatcher 带失败记录直连定稿。"""

    runs = InMemoryTripRunStore()
    run_id = await _running_run(runs)
    state = _sealed_state(run_id).model_copy(
        update={"last_error": "earlier research failure"}
    )
    assert state.run_deadline is not None
    deadline_observation("expired")

    update = await dispatch.dispatcher_node(state)
    record = update["delivery_failure"]
    assert record.failure_class is InternalFailureClass.RESEARCH_GAP
    assert record.operation == "deadline_closeout"
    assert record.attempts == 1 and record.retry_exhausted is True

    state = state.model_copy(update=update)
    assert dispatch.route_after_dispatcher(state) == NODE_DELIVERY_FINALIZER

    bundles = InMemoryDeliveryBundleStore()
    config = {"configurable": {"trip_run_store": runs, "delivery_bundle_store": bundles}}
    with pytest.raises(DeliveryFinalizationError) as exc_info:
        await delivery_finalizer_node(state, config)
    assert str(exc_info.value.__cause__) == "deadline_closeout"

    stored = await runs.get_run(run_id)
    assert stored is not None and stored.status is TripRunStatus.FAILED
    assert runs.events[run_id][-1].event_type == "run.delivery_failed"


async def test_closeout_with_workspace_still_projects_and_commits(
    deadline_observation,
) -> None:
    """已有组合时窗口关闭仍正常投影并提交交付。"""

    runs = InMemoryTripRunStore()
    run_id = await _running_run(runs)
    workspace = _workspace(run_id)
    state = _sealed_state(run_id).model_copy(
        update={"trip_workspace": workspace, "weather_context": _weather(workspace)}
    )
    deadline_observation("closeout")

    update = await dispatch.dispatcher_node(state)
    assert "delivery_failure" not in update
    state = state.model_copy(update=update)
    # 无失败记录时仍收敛到 to_check，由图的 dispatcher 条件边映射到 projector。
    assert dispatch.route_after_dispatcher(state) == "to_check"
    graph = build_travel_workflow()
    branch = graph.branches[NODE_DISPATCHER]["_route_after_dispatcher_with_amendments"]
    assert branch.ends["to_check"] == NODE_DELIVERY_PROJECTOR
    assert branch.ends[NODE_DELIVERY_FINALIZER] == NODE_DELIVERY_FINALIZER

    state = state.model_copy(update=await delivery_projection_node(state))
    bundles = InMemoryDeliveryBundleStore()
    config = {"configurable": {"trip_run_store": runs, "delivery_bundle_store": bundles}}
    state = state.model_copy(update=await delivery_finalizer_node(state, config))

    stored = await runs.get_run(run_id)
    assert stored is not None and stored.status is TripRunStatus.COMPLETED
    assert state.delivery_persisted is True
    current = await bundles.get_current(run_id)
    assert current is not None
