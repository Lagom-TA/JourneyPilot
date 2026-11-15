import asyncio
from datetime import date

import pytest

from tests.fixtures.itinerary import (
    itinerary_draft,
    meal_placement,
    restore_planning_state,
    visit_entry,
)
from tests.fixtures.planning_state import make_planning_state
from tests.fixtures.research_catalog import make_catalog
from tests.planning.itinerary.test_revision import (
    restaurant_packet,
    route_packet,
    visit_packet,
)
from travel_agent.planning.itinerary import node
from travel_agent.planning.itinerary.draft import ItineraryCompositionDraft
from travel_agent.runtime.cancellation import RunCancelled
from travel_agent.storage.worker_journal_store import JournalConflict


@pytest.fixture
def conflict_state():
    payload = itinerary_draft([meal_placement(), visit_entry("09:10", "10:10")])
    payload["days"][0]["day_design"] = {
        "free_time": [{
            "planned_start": "2026-10-10T15:00:00+09:00",
            "planned_end": "2026-10-10T15:30:00+09:00",
        }],
    }
    payload["duration_days"] = 2
    payload["days"].append({
        "day_id": "day_2",
        "day": 2,
        "date": "2026-10-11",
        "destination_id": "destination_tokyo",
        "placements": [meal_placement(day="2026-10-11")],
    })
    catalog = make_catalog(restaurant_packet(), visit_packet(), route_packet())
    original = make_planning_state()
    shell = original.minimum_delivery_draft.day_shells[0]
    return restore_planning_state(
        original,
        controlled_trip_identity={
            **original.controlled_trip_identity,
            "end_date": "2026-10-11",
        },
        minimum_delivery_draft=original.minimum_delivery_draft.model_copy(update={
            "day_shells": [
                shell.model_copy(update={"lodging_night": True}),
                shell.model_copy(update={
                    "day_id": "day_2", "day": 2, "date": date(2026, 10, 11),
                }),
            ],
        }),
        recommendation_catalog=catalog,
        fact_data_revision=catalog.fact_data_revision,
        placement_skeleton=ItineraryCompositionDraft.model_validate(payload),
        execution_plan=[["itinerary_planner"]],
        agent_status={"itinerary_planner": "pending"},
    )


@pytest.fixture(autouse=True)
def isolate_external_calls(monkeypatch):
    async def no_followup(*args, **kwargs):
        pytest.fail("已有路线时不应发起交通补查")

    async def no_reschedule(*args, **kwargs):
        pytest.fail("此时不应启动重排")

    async def no_tools():
        return []

    async def keep_skeleton(skeleton, *args, **kwargs):
        return skeleton

    async def keep_workspace(workspace, *args, **kwargs):
        return workspace

    monkeypatch.setattr(node, "research_transport_followup", no_followup)
    monkeypatch.setattr(node, "_compose_draft", no_reschedule)
    monkeypatch.setattr(node, "get_available_tools", no_tools)
    monkeypatch.setattr(node, "locate_authored_composition", keep_skeleton)
    monkeypatch.setattr(node, "complete_rail_route_paths", keep_workspace)
    monkeypatch.setattr(node, "write_itinerary_copy", keep_workspace)
    monkeypatch.setattr(node, "get_model_router", lambda: None)
    monkeypatch.setattr(node, "llm_for_task", lambda *args, **kwargs: object())


def assert_partial_closeout(state):
    assert state.agent_status["itinerary_planner"] == "completed"
    assert state.composition_failure_context is None
    assert state.composition_fallback_skeleton is None
    assert state.local_connector_gaps == []
    itinerary = state.trip_workspace.itinerary
    first, second = itinerary.day_plans
    assert first.date.isoformat() == "2026-10-10"
    assert first.timeline == []
    assert all(stop.day_id != first.day_id for stop in itinerary.visit_stops)
    assert all(stop.day_id != first.day_id for stop in itinerary.dining_stops)
    assert all(block.day_id != first.day_id for block in itinerary.custom_blocks)
    assert itinerary.transport_legs == []
    assert second.date.isoformat() == "2026-10-11"
    assert second.timeline
    assert [stop.day_id for stop in itinerary.dining_stops] == [second.day_id]
    assert any(
        "2026-10-10" in item
        and "尚未安排" in item
        and "60分钟" in item
        and "10分钟" in item
        for item in itinerary.unresolved
    )


def assert_pending_fallback(state, original):
    assert state.agent_status["itinerary_planner"] == "pending"
    assert state.trip_workspace is None
    assert state.placement_skeleton == original.placement_skeleton
    assert state.composition_reschedule_rounds == 1
    assert "路线约 60 分钟" in state.composition_failure_context
    assert "可用窗口 10 分钟" in state.composition_failure_context
    fallback = state.composition_fallback_skeleton
    assert fallback is not None
    assert fallback.days[0].placements == []
    assert fallback.days[0].day_design.free_time == []
    assert fallback.days[1] == original.placement_skeleton.days[1]


@pytest.mark.asyncio
async def test_insufficient_budget_delivers_partial_itinerary(monkeypatch, conflict_state):
    monkeypatch.setattr(node, "_can_reschedule", lambda: False)
    monkeypatch.setattr(node, "_remaining_materialization_seconds", lambda: 0.0)

    result = await node.itinerary_planner_node(conflict_state, {})
    completed = restore_planning_state(conflict_state, **result)

    assert completed.composition_reschedule_rounds == 0
    assert_partial_closeout(completed)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "composition_exhausted"])
async def test_failed_reschedule_delivers_saved_fallback(monkeypatch, conflict_state, failure):
    monkeypatch.setattr(node, "_can_reschedule", lambda: True)
    monkeypatch.setattr(node, "_remaining_materialization_seconds", lambda: 100.0)
    pending = restore_planning_state(
        conflict_state, **await node.itinerary_planner_node(conflict_state, {})
    )
    assert_pending_fallback(pending, conflict_state)
    calls = []

    async def failed_reschedule(state, *args, **kwargs):
        calls.append(state)
        if failure == "timeout":
            await asyncio.sleep(1)
            pytest.fail("重排应在预算到期时取消")
        raise node.CompositionTimeExhausted("no time for composition")

    monkeypatch.setattr(node, "_compose_draft", failed_reschedule)
    monkeypatch.setattr(node, "_remaining_materialization_seconds", lambda: 0.02)
    completed = restore_planning_state(
        pending, **await node.itinerary_planner_node(pending, {})
    )

    assert calls == [pending]
    assert_partial_closeout(completed)


@pytest.mark.asyncio
async def test_exhausted_reschedule_rounds_never_deliver_conflicting_route(
    monkeypatch, conflict_state,
):
    monkeypatch.setattr(node, "_can_reschedule", lambda: True)
    monkeypatch.setattr(node, "_remaining_materialization_seconds", lambda: 100.0)
    pending = restore_planning_state(
        conflict_state, **await node.itinerary_planner_node(conflict_state, {})
    )
    assert_pending_fallback(pending, conflict_state)
    calls = []

    async def still_conflicting(state, *args, **kwargs):
        calls.append(state)
        return state.placement_skeleton

    monkeypatch.setattr(node, "_compose_draft", still_conflicting)
    redrafted = restore_planning_state(
        pending, **await node.itinerary_planner_node(pending, {})
    )
    assert redrafted.agent_status["itinerary_planner"] == "pending"
    assert redrafted.composition_reschedule_rounds == 1
    assert redrafted.composition_failure_context is None
    assert redrafted.composition_fallback_skeleton == pending.composition_fallback_skeleton

    completed = restore_planning_state(
        redrafted, **await node.itinerary_planner_node(redrafted, {})
    )
    assert calls == [pending]
    assert_partial_closeout(completed)


@pytest.mark.asyncio
async def test_reschedule_propagates_control_exceptions(monkeypatch, conflict_state):
    monkeypatch.setattr(node, "_can_reschedule", lambda: True)
    monkeypatch.setattr(node, "_remaining_materialization_seconds", lambda: 100.0)
    pending = restore_planning_state(
        conflict_state, **await node.itinerary_planner_node(conflict_state, {})
    )
    assert_pending_fallback(pending, conflict_state)

    for error in (RunCancelled("run_test"), JournalConflict("conflict")):
        async def interrupted(*args, **kwargs):
            raise error

        monkeypatch.setattr(node, "_compose_draft", interrupted)
        with pytest.raises(type(error)) as raised:
            await node.itinerary_planner_node(pending, {})
        assert raised.value is error
