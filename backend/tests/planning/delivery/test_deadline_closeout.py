"""研究窗口关闭时的交付收口：没有组合就记失败记录，有组合就走正常投影。

dispatcher 只在研究已收口且不欠组合时走到这里；若此时没有任何 workspace，
继续投影会抛 `ValueError("delivery projections require the composed workspace")`，
所以它带一条 `DeliveryFailureRecord` 直连交付定稿。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

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
)
from travel_agent.planning.outcomes import InternalFailureClass
from travel_agent.planning.requirements.generation_contracts import PlanningGeneration
from travel_agent.planning.research import dispatch
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.weather.models import WeatherContextSnapshot
from travel_agent.runtime.deadlines import DeadlineObservation
from travel_agent.runtime.run_contracts import TripRunStatus


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


async def test_closeout_without_workspace_marks_the_run_failed(
    deadline_observation,
) -> None:
    """没有 workspace 时不进 projector：dispatcher 带失败记录直连定稿。"""

    runs = InMemoryTripRunStore()
    run_id = await _running_run(runs)
    state = _sealed_state(run_id)
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
    with pytest.raises(DeliveryFinalizationError):
        await delivery_finalizer_node(state, config)

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
