import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from tests.fixtures.planning_state import make_planning_state
from travel_agent.planning.itinerary import composition
from travel_agent.planning.itinerary.draft import ItineraryCompositionDraft
from travel_agent.planning.itinerary.prompts import _build_composition_prompt
from travel_agent.planning.requirements.inputs import MinimumDeliveryDayShell
from travel_agent.tools.result import ReactOutcome


def test_user_requirements_are_injected_as_planning_guidance():
    original = make_planning_state().model_copy(
        update={
            "current_requirements": "必去东京国立博物馆，喜欢建筑摄影，住在东京站附近",
        }
    )
    changed = original.model_copy(
        update={
            "run_id": "another",
            "composition_failure_context": "itinerary composition does not match the required structure",
            "session_anchor": {
                "summary": "prior Tokyo fact",
                "key_constraints": ["不要爬楼"],
            },
        }
    )
    first = _build_composition_prompt(original, "Tokyo museum")
    second = _build_composition_prompt(changed, "Tokyo dining")

    assert first.system == second.system
    assert first.runtime != second.runtime
    assert "Tokyo dining" not in second.system
    assert "不要爬楼" not in second.runtime
    assert "prior Tokyo fact" not in second.runtime
    assert "必去东京国立博物馆" in first.runtime
    assert "<user_requirements>" in first.runtime
    assert "<json_schema>" in second.runtime and "<json_schema>" not in second.system
    assert "does not match the required structure" in second.runtime


def test_composition_prompt_has_no_acceptance_or_gate_wording():
    prompt = _build_composition_prompt(make_planning_state(), "Tokyo museum")
    combined = prompt.system + prompt.runtime
    for phrase in ("验收", "忠实度", "never_violate", "repair_then_deviate", "Composition Rules", "必须覆盖", "整份组合被拒", "回炉"):
        assert phrase not in combined
    assert "结合旅行理解与研究成果安排旅程" in prompt.system


def _unplanned_days_state(count):
    state = make_planning_state()
    start = date(2026, 10, 10)
    shells = [
        MinimumDeliveryDayShell(
            day_id=f"day_{index + 1}", day=index + 1,
            date=start + timedelta(days=index), destination_id="destination_tokyo",
            lodging_night=index < count - 1,
        )
        for index in range(count)
    ]
    draft = state.minimum_delivery_draft.model_copy(update={"day_shells": shells})
    identity = {**state.controlled_trip_identity, "end_date": shells[-1].date.isoformat()}
    state = state.model_copy(update={"minimum_delivery_draft": draft, "controlled_trip_identity": identity})
    days = [
        {"day_id": shell.day_id, "day": shell.day, "date": shell.date.isoformat(),
         "destination_id": shell.destination_id, "placements": [],
         "day_design": {"unresolved": [f"第 {shell.day} 天尚未安排"]}}
        for shell in shells
    ]
    return state, {"itinerary_id": "trip", "title": "旅行", "duration_days": count, "days": days}


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 14])
async def test_composition_keeps_each_confirmed_date_with_explicit_unplanned_days(monkeypatch, count):
    state, payload = _unplanned_days_state(count)

    async def react(**kwargs):
        return SimpleNamespace(outcome=ReactOutcome.FINAL_ANSWER, content=json.dumps(payload), tool_results=[])

    monkeypatch.setattr(composition, "streaming_react_loop", react)
    draft = await composition._compose_draft(state, "安排", object(), available_tools=[], tool_context={})

    assert [day.date for day in draft.days] == [day.date for day in state.minimum_delivery_draft.day_shells]
    assert all(not day.placements and day.day_design.unresolved for day in draft.days)


@pytest.mark.asyncio
async def test_composition_retries_when_confirmed_dates_are_missing(monkeypatch):
    state, payload = _unplanned_days_state(2)
    truncated = {**payload, "duration_days": 1, "days": payload["days"][:1]}
    responses = iter([truncated, payload])
    requests = []

    async def react(**kwargs):
        requests.append(list(kwargs["messages"]))
        return SimpleNamespace(outcome=ReactOutcome.FINAL_ANSWER, content=json.dumps(next(responses)), tool_results=[])

    monkeypatch.setattr(composition, "streaming_react_loop", react)
    draft = await composition._compose_draft(state, "安排", object(), available_tools=[], tool_context={})

    assert len(draft.days) == 2
    assert len(requests) == 2
    assert "行程日期必须与已确认的旅行日期逐日一致" in requests[1][-1]["content"]


def test_empty_day_requires_an_explicit_missing_item():
    _, payload = _unplanned_days_state(1)
    payload["days"][0]["day_design"] = {"unresolved": []}

    with pytest.raises(ValueError, match="unplanned day needs an unresolved explanation"):
        ItineraryCompositionDraft.model_validate(payload)
