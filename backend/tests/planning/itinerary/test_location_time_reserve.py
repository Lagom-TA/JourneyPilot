"""撰写地点定位共享时间预算的边界。"""

import asyncio

import pytest

from tests.fixtures.itinerary import itinerary_draft, visit_entry
from tests.fixtures.planning_state import make_planning_state
from travel_agent.planning.itinerary import locations
from travel_agent.planning.itinerary.draft import ItineraryCompositionDraft, authored_places
from travel_agent.runtime import operations
from travel_agent.runtime.cancellation import RunCancelled, run_control_registry
from travel_agent.runtime.context import current_run_id
from travel_agent.runtime.deadlines import DeadlineObservation
from travel_agent.storage.worker_journal_store import JournalConflict


def _draft(*names):
    entries = []
    for index, name in enumerate(names):
        entry = visit_entry(f"{9 + index:02d}:00", f"{10 + index:02d}:00")
        entry.pop("candidate_id")
        entry["authored_place"] = {
            "name": name,
            "local_name": name,
            "city": "Tokyo",
            "address": f"{name} address",
            "selection_reason": "参观博物馆",
            "visit_type": "culture",
            "highlights": ["展览"],
        }
        if name == "Existing":
            entry["authored_place"].update(
                resolved_place_id="existing",
                resolved_address="existing address",
                resolved_latitude=35.6,
                resolved_longitude=139.7,
            )
        entries.append(entry)
    return ItineraryCompositionDraft.model_validate(itinerary_draft(entries))


def _resolved(name):
    return {
        "place_id": f"id_{name}",
        "address": f"resolved {name}",
        "latitude": 35.6,
        "longitude": 139.7,
    }


@pytest.fixture(autouse=True)
def _no_real_tools(monkeypatch):
    monkeypatch.setattr(locations, "_authored_place_tool_access", lambda state: None)


@pytest.mark.asyncio
async def test_shared_budget_keeps_completed_entries_and_supports_resume(monkeypatch):
    draft = _draft("First", "First", "Slow", "Later", "Existing")
    calls = []
    slow_cancelled = False

    async def resolve(**kwargs):
        nonlocal slow_cancelled
        name = kwargs["name"]
        calls.append(name)
        if name == "Slow":
            try:
                await asyncio.sleep(1)
            finally:
                slow_cancelled = True
        return _resolved(name)

    monkeypatch.setattr(locations, "resolve_authored_place", resolve)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 0.05
    state = make_planning_state()
    result = await locations.locate_authored_composition(
        draft, state, remaining_seconds=lambda: deadline - loop.time()
    )
    places = [ref.place for ref in authored_places(result)]
    assert calls == ["First", "Slow"]
    assert slow_cancelled
    assert [place.resolved_place_id for place in places] == [
        "id_First", "id_First", None, None, "existing"
    ]
    assert places[2].name == "Slow" and places[3].name == "Later"
    assert not authored_places(draft)[0].place.is_located

    calls.clear()

    async def resume(**kwargs):
        calls.append(kwargs["name"])
        return _resolved(kwargs["name"])

    monkeypatch.setattr(locations, "resolve_authored_place", resume)
    resumed = await locations.locate_authored_composition(
        result, state, remaining_seconds=lambda: float("inf")
    )
    assert calls == ["Slow", "Later"]
    assert [ref.place.resolved_place_id for ref in authored_places(resumed)] == [
        "id_First", "id_First", "id_Slow", "id_Later", "existing"
    ]


@pytest.mark.asyncio
async def test_per_entry_limit_tracks_each_remaining_value_and_default(monkeypatch):
    timeouts = []
    remaining = iter([100.0, 3.0, float("inf")])

    async def wait_for(awaitable, timeout):
        timeouts.append(timeout)
        return await awaitable

    async def resolve(**kwargs):
        return None

    monkeypatch.setattr(locations.asyncio, "wait_for", wait_for)
    monkeypatch.setattr(locations, "resolve_authored_place", resolve)
    draft = _draft("One", "Two", "Three")
    state = make_planning_state()
    await locations.locate_authored_composition(
        draft, state, remaining_seconds=lambda: next(remaining)
    )
    assert timeouts == [20.0, 3.0, 20.0]
    timeouts.clear()
    await locations.locate_authored_composition(draft, state)
    assert timeouts == [20.0, 20.0, 20.0]


@pytest.mark.asyncio
async def test_zero_budget_does_not_resolve(monkeypatch):
    async def resolve(**kwargs):
        pytest.fail("zero budget must not invoke a provider")

    monkeypatch.setattr(locations, "resolve_authored_place", resolve)
    draft = _draft("One", "Existing")
    result = await locations.locate_authored_composition(
        draft, make_planning_state(), remaining_seconds=lambda: 0.0
    )
    assert result is draft


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["user_cancel", "lease_lost"])
async def test_zero_budget_does_not_hide_pending_cancellation(reason):
    run_id = "location-budget-cancel"
    handle = run_control_registry.register(run_id)
    token = current_run_id.set(run_id)
    handle.request_stop(reason)
    try:
        with pytest.raises(RunCancelled) as raised:
            await locations.locate_authored_composition(
                _draft("One"), make_planning_state(), remaining_seconds=lambda: 0.0
            )
        assert raised.value.reason == reason
    finally:
        current_run_id.reset(token)
        run_control_registry.unregister(run_id, handle)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [RunCancelled("run_test"), JournalConflict("conflict"), asyncio.CancelledError()],
)
async def test_control_exceptions_from_resolver_propagate(monkeypatch, error):
    async def resolve(**kwargs):
        raise error

    monkeypatch.setattr(locations, "resolve_authored_place", resolve)
    with pytest.raises(type(error)):
        await locations.locate_authored_composition(
            _draft("One"), make_planning_state(), remaining_seconds=lambda: 0.1
        )


@pytest.mark.asyncio
async def test_model_window_still_limits_resolution(monkeypatch):
    calls = []
    cancelled = False

    async def resolve(**kwargs):
        nonlocal cancelled
        calls.append(kwargs["name"])
        if kwargs["name"] == "Slow":
            try:
                await asyncio.sleep(1)
            finally:
                cancelled = True
        return _resolved(kwargs["name"])

    observation = DeadlineObservation(
        elapsed_seconds=10.0, remaining_seconds=5.0, phase="composition_closed"
    )
    monkeypatch.setattr(locations, "resolve_authored_place", resolve)
    monkeypatch.setattr(operations, "remaining_model_seconds", lambda operation: 0.02)
    monkeypatch.setattr(
        operations, "observe_current_run_deadline", lambda: (None, observation)
    )
    result = await locations.locate_authored_composition(
        _draft("First", "Slow", "Later"),
        make_planning_state(),
        remaining_seconds=lambda: float("inf"),
    )
    assert calls == ["First", "Slow"] and cancelled
    assert [ref.place.resolved_place_id for ref in authored_places(result)] == [
        "id_First", None, None
    ]
