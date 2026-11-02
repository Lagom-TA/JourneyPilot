from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from tests.fixtures.research_catalog import make_visit_packet
from travel_agent.integrations.weather_contracts import WeatherTimeWindow
from travel_agent.planning.itinerary.selection import _slot
from travel_agent.planning.references import EntityRef, EntityType
from travel_agent.planning.research.candidates import DiningCandidate, LodgingCandidate
from travel_agent.planning.weather.adjustments import (
    _replacement_operation,
    build_weather_adjustment_proposals,
)
from travel_agent.planning.weather.models import (
    WeatherDayContext,
    WeatherImpact,
    WeatherSensitivity,
)


def test_candidate_weather_impact_targets_scheduled_visits_on_the_affected_day():
    first_day, second_day = date(2026, 11, 6), date(2026, 11, 7)
    visits = [
        SimpleNamespace(item_id="visit-1", name="拙政园", lineage=SimpleNamespace(candidate_id="candidate-1")),
        SimpleNamespace(item_id="visit-2", name="园林漫步", lineage=SimpleNamespace(candidate_id="candidate-1")),
        SimpleNamespace(item_id="visit-3", name="第二天活动", lineage=SimpleNamespace(candidate_id="candidate-1")),
        SimpleNamespace(item_id="visit-other", name="另一景点", lineage=SimpleNamespace(candidate_id="candidate-2")),
    ]

    def entry(entity_id):
        return EntityRef(entity_type=EntityType.VISIT_STOP, entity_id=entity_id)

    itinerary = SimpleNamespace(
        visit_stops=visits,
        dining_stops=[], lodging_stays=[], transport_legs=[], custom_blocks=[],
        day_plans=[
            SimpleNamespace(day_id="day-1", date=first_day, timeline=[entry("visit-1"), entry("visit-2"), entry("visit-other")]),
            SimpleNamespace(day_id="day-2", date=second_day, timeline=[entry("visit-3")]),
        ],
    )
    impact = WeatherImpact(
        weather_impact_id="wind-1", date=first_day,
        target_ref=entry("candidate-1"), condition_type="wind",
        severity="medium", action="add_buffer", fact_assertion_ids=["weather-fact"],
        data_kind="forecast", trigger_code="wind",
    )
    weather = SimpleNamespace(impacts=[impact], days=[], weather_data_revision=0)
    bundle = SimpleNamespace(
        workspace=SimpleNamespace(itinerary=itinerary, workspace_revision=0),
        weather_snapshot=SimpleNamespace(impacts=[], adjustment_proposals=[]),
    )

    proposals = build_weather_adjustment_proposals(bundle, weather, previous_impacts={})

    assert len(proposals) == 1
    assert proposals[0].weather_impact_ids == ["wind-1"]
    assert "拙政园" in proposals[0].summary
    assert "园林漫步" in proposals[0].summary
    assert "30 分钟" in proposals[0].summary
    assert {operation.target_entity_id for operation in proposals[0].operations} == {"visit-1", "visit-2"}
    assert all(operation.day_id == "day-1" for operation in proposals[0].operations)


def test_weather_replacement_stays_in_the_same_destination():
    trip_date = date(2026, 11, 6)
    current = make_visit_packet("current", "当前景点").candidates[0]
    another_city = make_visit_packet("other-city", "外地景点").candidates[0].model_copy(
        update={"destination_id": "other-city"}
    )
    same_city = make_visit_packet("same-city", "本地景点").candidates[0]
    candidates = {item.candidate_id: item for item in (current, another_city)}
    visit = SimpleNamespace(
        item_id="visit-1",
        place_id=current.place_id,
        lineage=SimpleNamespace(lineage_kind="candidate_entity", candidate_id=current.candidate_id),
    )
    bundle = SimpleNamespace(workspace=SimpleNamespace(
        itinerary=SimpleNamespace(visit_stops=[visit]),
        selection_slots=[],
        recommendation_catalog=SimpleNamespace(candidate_index=lambda: candidates),
    ))
    weather = SimpleNamespace(days=[WeatherDayContext(
        destination_id=current.destination_id, date=trip_date, timezone="Asia/Tokyo",
        latitude=35.6, longitude=139.6, data_kind="forecast",
    )])
    impact = WeatherImpact(
        weather_impact_id="rain-1", date=trip_date,
        target_ref=EntityRef(entity_type=EntityType.VISIT_STOP, entity_id="visit-1"),
        condition_type="rain", severity="high", action="replace",
        fact_assertion_ids=["weather-fact"], data_kind="forecast", trigger_code="rain",
    )

    assert _replacement_operation(bundle, weather, impact, "visit-1") is None
    candidates[same_city.candidate_id] = same_city
    replacement = _replacement_operation(bundle, weather, impact, "visit-1")
    assert replacement is not None
    assert replacement.candidate_id == same_city.candidate_id


_TRIP_DATE = date(2026, 11, 6)


def _weather_candidate(candidate_id, *, indoor=False):
    candidate = make_visit_packet(candidate_id, candidate_id).candidates[0]
    sensitivity = WeatherSensitivity(
        exposure="indoor" if indoor else "outdoor",
        rain_sensitivity="none" if indoor else "high",
        heat_sensitivity="none" if indoor else "high",
        cold_sensitivity="none",
        wind_sensitivity="none",
        requires_clear_visibility=False,
    )
    return candidate.model_copy(
        update={"destination_id": "city-b", "weather_sensitivity": sensitivity}
    )


def _visit_bundle(candidates, placements, *, slots=()):
    visits = []
    dates = {}
    for item_id, candidate, day_date in placements:
        start = datetime.fromisoformat(f"{day_date}T10:00:00+08:00")
        visits.append(SimpleNamespace(
            item_id=item_id,
            name=candidate.name,
            place_id=candidate.place_id,
            planned_start=start,
            planned_end=start + timedelta(minutes=90),
            duration_minutes=90,
            lineage=SimpleNamespace(
                lineage_kind="candidate_entity", candidate_id=candidate.candidate_id,
            ),
        ))
        dates.setdefault(day_date, []).append(
            EntityRef(entity_type=EntityType.VISIT_STOP, entity_id=item_id)
        )
    itinerary = SimpleNamespace(
        visit_stops=visits, dining_stops=[], lodging_stays=[], transport_legs=[],
        custom_blocks=[],
        day_plans=[
            SimpleNamespace(day_id=f"day-{day_date}", date=day_date,
                            destination_id="city-b", timeline=timeline)
            for day_date, timeline in sorted(dates.items())
        ],
    )
    candidate_index = {item.candidate_id: item for item in candidates}
    return SimpleNamespace(
        workspace=SimpleNamespace(
            itinerary=itinerary, selection_slots=list(slots), workspace_revision=0,
            recommendation_catalog=SimpleNamespace(candidate_index=lambda: candidate_index),
        ),
        weather_snapshot=SimpleNamespace(impacts=[], adjustment_proposals=[]),
    )


def _weather_day(destination_id, day_date, *, rain=0, windows=()):
    return WeatherDayContext(
        destination_id=destination_id, date=day_date, timezone="Asia/Shanghai",
        latitude=30, longitude=120, data_kind="forecast",
        precipitation_probability_pct=rain, hourly_windows=list(windows),
        fact_assertion_ids=[f"weather-{destination_id}-{day_date}"],
    )


def _impact(target_id, *, condition, severity, action):
    return WeatherImpact(
        weather_impact_id="impact", date=_TRIP_DATE,
        target_ref=EntityRef(entity_type=EntityType.VISIT_STOP, entity_id=target_id),
        condition_type=condition, severity=severity, action=action,
        fact_assertion_ids=["weather-fact"], data_kind="forecast", trigger_code=condition,
    )


def _proposals(bundle, impact, days):
    weather = SimpleNamespace(days=days, impacts=[impact], weather_data_revision=0)
    return build_weather_adjustment_proposals(bundle, weather, previous_impacts={})


def _selection_candidate(kind, candidate_id, *, indoor=False):
    base = _weather_candidate(candidate_id, indoor=indoor)
    model = DiningCandidate if kind == "dining" else LodgingCandidate
    fields = {
        name: value
        for name, value in base.model_dump().items()
        if name in model.model_fields and name != "candidate_kind"
    }
    fields["availability_status"] = "needs_confirmation"
    if kind == "dining":
        fields.update(branch_name=candidate_id, meal_types=["lunch"])
    else:
        fields.update(
            property_name=candidate_id,
            check_in_date=_TRIP_DATE - timedelta(days=1),
            check_out_date=_TRIP_DATE + timedelta(days=2),
            nights=3,
        )
    return model(**fields)


@pytest.mark.parametrize("kind", ["dining", "lodging"])
@pytest.mark.parametrize("target_kind", ["candidate", "entity"])
def test_selection_replacement_uses_its_destination_weather(kind, target_kind):
    current = _selection_candidate(kind, "current")
    outdoor = _selection_candidate(kind, "outdoor")
    indoor = _selection_candidate(kind, "indoor", indoor=True)
    entity_id = "target-1"
    entity_type = EntityType.DINING_STOP if kind == "dining" else EntityType.LODGING_STAY
    slot = _slot(
        selected=current, eligible=[outdoor, indoor], slot_id="slot-1",
        target_entity_id=entity_id, slot_type=kind, context={},
    )
    entity = SimpleNamespace(
        item_id=entity_id, stay_id=entity_id, name="target",
        lineage=SimpleNamespace(candidate_id=current.candidate_id),
        check_in_date=_TRIP_DATE - timedelta(days=1),
        check_out_date=_TRIP_DATE + timedelta(days=2),
    )
    itinerary = SimpleNamespace(
        visit_stops=[], dining_stops=[entity] if kind == "dining" else [],
        lodging_stays=[entity] if kind == "lodging" else [], transport_legs=[],
        custom_blocks=[],
        # The middle night of a lodging stay has no check-in/out timeline entry.
        day_plans=[SimpleNamespace(
            day_id="day-1", date=_TRIP_DATE, destination_id="city-b",
            timeline=[EntityRef(entity_type=entity_type, entity_id=entity_id)]
            if kind == "dining" else [],
        )],
    )
    candidates = {item.candidate_id: item for item in (current, outdoor, indoor)}
    bundle = SimpleNamespace(
        workspace=SimpleNamespace(
            itinerary=itinerary, selection_slots=[slot], workspace_revision=0,
            recommendation_catalog=SimpleNamespace(candidate_index=lambda: candidates),
        ),
        weather_snapshot=SimpleNamespace(impacts=[], adjustment_proposals=[]),
    )
    impact = _impact(
        current.candidate_id if target_kind == "candidate" else entity_id,
        condition="rain", severity="high", action="replace",
    ).model_copy(update={"target_ref": EntityRef(
        entity_type=entity_type,
        entity_id=current.candidate_id if target_kind == "candidate" else entity_id,
    )})
    days = [_weather_day("city-a", _TRIP_DATE), _weather_day("city-b", _TRIP_DATE, rain=100)]

    proposals = _proposals(bundle, impact, days)

    expected = next(option for option in slot.options if option.candidate_id == indoor.candidate_id)
    assert len(proposals) == 1
    assert proposals[0].operations[0].option_id == expected.option_id


@pytest.mark.parametrize("target_kind", ["candidate", "entity"])
@pytest.mark.parametrize("other_city_first", [True, False])
def test_replacement_uses_the_affected_destination_weather(target_kind, other_city_first):
    current = _weather_candidate("current")
    outdoor = _weather_candidate("a-outdoor")
    indoor = _weather_candidate("b-indoor", indoor=True)
    bundle = _visit_bundle(
        [current, outdoor, indoor], [("visit-1", current, _TRIP_DATE)],
    )
    impact = _impact(
        current.candidate_id if target_kind == "candidate" else "visit-1",
        condition="rain", severity="high", action="replace",
    )
    other_city = _weather_day("city-a", _TRIP_DATE)
    affected_city = _weather_day("city-b", _TRIP_DATE, rain=100)
    days = [other_city, affected_city] if other_city_first else [affected_city, other_city]

    proposals = _proposals(bundle, impact, days)

    assert len(proposals) == 1
    assert proposals[0].operations[0].candidate_id == indoor.candidate_id


@pytest.mark.parametrize(
    ("target_kind", "has_affected_weather"),
    [("candidate", True), ("entity", True), ("authored", True), ("entity", False)],
)
def test_reschedule_uses_only_the_affected_destination_and_date(
    target_kind, has_affected_weather,
):
    current = _weather_candidate("current")
    bundle = _visit_bundle([current], [("visit-1", current, _TRIP_DATE)])
    if target_kind == "authored":
        bundle.workspace.itinerary.visit_stops[0].lineage = SimpleNamespace(
            lineage_kind="authored_entity", candidate_id=None,
        )
    impact = _impact(
        current.candidate_id if target_kind == "candidate" else "visit-1",
        condition="heat", severity="medium", action="move_time",
    )

    def window(day_date, hour, temperature):
        start = datetime.fromisoformat(f"{day_date}T{hour:02}:00:00+08:00")
        return WeatherTimeWindow(
            start_at=start, end_at=start + timedelta(hours=1),
            apparent_temperature_c=temperature,
        )

    days = [
        _weather_day("city-a", _TRIP_DATE, windows=[window(_TRIP_DATE, 8, 10)]),
        _weather_day("city-b", _TRIP_DATE - timedelta(days=1),
                     windows=[window(_TRIP_DATE - timedelta(days=1), 9, 15)]),
    ]
    if has_affected_weather:
        days.append(_weather_day("city-b", _TRIP_DATE, windows=[
            window(_TRIP_DATE, 14, 35), window(_TRIP_DATE, 18, 25),
        ]))

    proposals = _proposals(bundle, impact, days)

    if not has_affected_weather:
        assert proposals == []
    else:
        assert len(proposals) == 1
        assert proposals[0].operations[0].planned_start.hour == 18


@pytest.mark.parametrize("with_slot", [True, False])
@pytest.mark.parametrize("has_unused_option", [True, False])
def test_replacement_never_suggests_a_scheduled_place(with_slot, has_unused_option):
    current = _weather_candidate("current")
    scheduled = _weather_candidate("a-scheduled", indoor=True)
    same_place = _weather_candidate("b-same-place", indoor=True).model_copy(
        update={"place_id": scheduled.place_id}
    )
    unused = _weather_candidate("c-unused", indoor=True)
    outside_slot = _weather_candidate("0-outside-slot", indoor=True)
    eligible = [scheduled, same_place, *([unused] if has_unused_option else [])]
    candidates = [current, *eligible, *([outside_slot] if with_slot else [])]
    slots = [
        _slot(
            selected=current, eligible=eligible, slot_id="slot-1",
            target_entity_id="visit-1", slot_type="visit", context={},
        )
    ] if with_slot else []
    bundle = _visit_bundle(
        candidates,
        [("visit-1", current, _TRIP_DATE),
         ("visit-2", scheduled, _TRIP_DATE + timedelta(days=1))],
        slots=slots,
    )
    impact = _impact(current.candidate_id, condition="rain", severity="high", action="replace")

    proposals = _proposals(bundle, impact, [_weather_day("city-b", _TRIP_DATE, rain=100)])

    if has_unused_option:
        assert len(proposals) == 1
        assert proposals[0].operations[0].candidate_id == unused.candidate_id
    else:
        assert proposals == []
