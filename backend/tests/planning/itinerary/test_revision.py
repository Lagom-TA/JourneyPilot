
import json
from datetime import date, datetime, timedelta

import pytest

from tests.fixtures.itinerary import (
    itinerary_draft,
    meal_placement,
    restore_planning_state,
    visit_entry,
)
from tests.fixtures.planning_state import make_planning_state
from tests.fixtures.research_catalog import (
    make_catalog,
    make_local_transport_packet,
    make_visit_packet,
)
from travel_agent.planning.itinerary import composition, connector_estimates, locations
from travel_agent.planning.itinerary.connectors import (
    extract_local_connector_gaps,
    materialize_skeleton_connectors,
)
from travel_agent.planning.itinerary.draft import (
    AuthoredRoute,
    ItineraryCompositionDraft,
    placement_occurrence_key,
)
from travel_agent.planning.itinerary.materialize import materialize_trip_workspace
from travel_agent.planning.itinerary.node import _composition_phase
from travel_agent.planning.itinerary.parsing import parse_itinerary_composition
from travel_agent.planning.itinerary.prompts import _build_composition_prompt
from travel_agent.planning.requirements.snapshot_contracts import IntentContractSnapshot
from travel_agent.planning.research.candidates import DiningCandidate
from travel_agent.planning.research.discovery_contracts import CandidateDiscoveryOrigin
from travel_agent.planning.research.packets import ResearchPacket


def visit_packet(candidate_id="candidate_visit"):
    return make_visit_packet(
        candidate_id,
        candidate_id,
        origin=CandidateDiscoveryOrigin.INTENT_QUERY,
        query_id=f"query_{candidate_id}",
        intent_id="intent_test",
    )


def restaurant_packet(candidate_id="candidate_dining"):
    packet = visit_packet(candidate_id)
    original = packet.candidates[0].model_dump()
    data = {
        key: value
        for key, value in original.items()
        if key in DiningCandidate.model_fields
    }
    data.update(
        candidate_kind="dining",
        branch_name="Cafe",
        meal_types=["breakfast", "lunch", "dinner"],
        availability_status="needs_confirmation",
        provider_place_type="restaurant",
    )
    payload = packet.model_dump()
    payload["candidates"] = [DiningCandidate.model_validate(data).model_dump()]
    return ResearchPacket.model_validate(payload)


def with_provider_coordinates(packet, *, destination_id="destination_tokyo", **updates):
    candidate = packet.candidates[0].model_copy(
        update={"destination_id": destination_id, **updates}
    )
    source = packet.source_records[0].model_copy(
        update={
            "snapshot": {
                "results": [
                    {
                        "place_id": candidate.place_id,
                        "latitude": 35.6,
                        "longitude": 139.7,
                    }
                ]
            }
        }
    )
    return packet.model_copy(
        update={"candidates": [candidate], "source_records": [source]}
    )


def authored_visit(name="Museum district", start="10:00", end="11:00"):
    entry = visit_entry(start, end)
    entry.pop("candidate_id")
    entry["selection_reason"] = "旧景点排程理由"
    entry["authored_place"] = {
        "name": name,
        "local_name": name,
        "city": "Tokyo",
        "address": "Tokyo",
        "selection_reason": "旧景点实体理由",
        "visit_type": "culture",
        "highlights": ["旧景点描述"],
    }
    return entry


def authored_dining(name="Restaurant area", start="18:00", end="19:00"):
    entry = meal_placement("dinner", start, end)
    entry.pop("candidate_id")
    entry["selection_reason"] = "旧餐厅排程理由"
    entry["authored_place"] = {
        "name": name,
        "local_name": name,
        "city": "Tokyo",
        "address": "Tokyo",
        "selection_reason": "旧餐厅实体理由",
        "cuisine_types": ["旧菜系"],
        "recommended_dishes": ["旧菜品"],
    }
    return entry


def workspace(composition, catalog, *, intent_spec=None):
    spec = intent_spec or make_planning_state().intent_spec
    return materialize_trip_workspace(
        run_id="run_test",
        workspace_revision=0,
        composition=composition,
        catalog=catalog,
        intent_contract_snapshot=IntentContractSnapshot.from_intent_spec(spec),
        composition_mutations=[],
    )


def connect(skeleton, catalog):
    gaps = extract_local_connector_gaps(
        skeleton, catalog, weather_data_revision=0
    )
    routes = {
        gap.gap_id: AuthoredRoute(
            mode="bus", duration_minutes=2, selection_reason="相邻地点短途公交"
        )
        for gap in gaps
    }
    result = materialize_skeleton_connectors(skeleton, catalog, gaps, routes)
    return gaps, ItineraryCompositionDraft.model_validate(result.model_dump())


def long_distance_packet(candidate_id, origin, destination, start, end, scope):
    packet = make_local_transport_packet(
        candidate_id, origin_place_id=origin, destination_place_id=destination
    )
    payload = packet.model_dump()
    candidate = payload["candidates"][0]
    candidate.update(
        transport_class="long_distance",
        provider_evidence_scope_id=scope,
        departure_at=datetime.fromisoformat(start),
        arrival_at=datetime.fromisoformat(end),
    )
    return ResearchPacket.model_validate(payload)


def transport(candidate_id):
    return {"placement_kind": "transport", "candidate_id": candidate_id}


def test_repeated_restaurant_is_an_occurrence_not_a_global_identity():
    payload = itinerary_draft([meal_placement(), meal_placement("lunch", "12:00", "13:00")])
    payload["days"].append(
        {
            **payload["days"][0],
            "day_id": "day_2",
            "day": 2,
            "date": "2026-10-11",
            "placements": [meal_placement(day="2026-10-11")],
        }
    )
    payload["duration_days"] = 2
    result = parse_itinerary_composition(json.dumps(payload))
    assert [len(day.placements) for day in result.days] == [2, 1]


@pytest.mark.asyncio
@pytest.mark.parametrize("cross_day", [False, True], ids=["different-meals", "different-days"])
async def test_planner_preserves_useful_restaurant_reuse_through_checkpoint(
    monkeypatch, cross_day,
):
    from travel_agent.planning.itinerary import node

    original = make_planning_state()
    payload = itinerary_draft([meal_placement()])
    if cross_day:
        payload["duration_days"] = 2
        payload["days"].append({
            **payload["days"][0],
            "day_id": "day_2", "day": 2, "date": "2026-10-11",
            "placements": [meal_placement(day="2026-10-11")],
        })
        shell = original.minimum_delivery_draft.day_shells[0]
        original = restore_planning_state(
            original,
            controlled_trip_identity={
                **original.controlled_trip_identity, "end_date": "2026-10-11",
            },
            minimum_delivery_draft=original.minimum_delivery_draft.model_copy(update={
                "day_shells": [
                    shell.model_copy(update={"lodging_night": True}),
                    shell.model_copy(update={
                        "day_id": "day_2", "day": 2, "date": date(2026, 10, 11),
                    }),
                ],
            }),
        )
    else:
        payload["days"][0]["placements"].append(meal_placement("lunch", "12:00", "13:00"))
    placements = [item for day in payload["days"] for item in day["placements"]]
    reasons = ["早餐顺路", "重访喜欢的门店品尝另一道菜"]
    for placement, reason in zip(placements, reasons):
        placement["selection_reason"] = reason
    catalog = make_catalog(restaurant_packet())
    calls = []

    class Model:
        async def ainvoke(self, messages, **kwargs):
            calls.append(messages)
            assert "不同餐次" in messages[0]["content"]
            assert "包括跨日复用" in messages[0]["content"]
            assert "不要求全程地点唯一" in messages[0]["content"]
            return json.dumps(payload)

    monkeypatch.setattr(node, "get_model_router", lambda: None)
    monkeypatch.setattr(node, "llm_for_task", lambda *args: Model())
    current = restore_planning_state(original, recommendation_catalog=catalog)
    drafted = restore_planning_state(current, **await node.itinerary_planner_node(current, {}))
    assert drafted.composition_failure_context is None
    assert drafted.placement_skeleton is not None
    assert len(calls) == 1
    completed = restore_planning_state(drafted, **await node.itinerary_planner_node(drafted, {}))
    assert completed.agent_status["itinerary_planner"] == "completed"
    stops = completed.trip_workspace_v2.itinerary.dining_stops
    assert len({stop.item_id for stop in stops}) == 2
    assert [stop.lineage.candidate_id for stop in stops] == ["candidate_dining"] * 2
    assert [stop.day_id for stop in stops] == [
        day["day_id"] for day in payload["days"] for _ in day["placements"]
    ]
    assert [stop.meal_type for stop in stops] == [item["meal_type"] for item in placements]
    assert [(stop.planned_start.isoformat(), stop.planned_end.isoformat()) for stop in stops] == [
        (item["planned_start"], item["planned_end"]) for item in placements
    ]
    assert [stop.selection_reason for stop in stops] == reasons
    repeated = restore_planning_state(drafted, **await node.itinerary_planner_node(drafted, {}))
    assert [stop.item_id for stop in repeated.trip_workspace_v2.itinerary.dining_stops] == [stop.item_id for stop in stops]
    assert len(calls) == 1


def test_duplicate_same_meal_is_reported_not_removed():
    with pytest.raises(ValueError, match="duplicate|more than once"):
        parse_itinerary_composition(json.dumps(itinerary_draft([meal_placement(), meal_placement()])))


def test_short_valid_transition_is_not_shifted():
    payload = itinerary_draft([meal_placement(), visit_entry("09:05", "10:05")])
    result = parse_itinerary_composition(json.dumps(payload))
    catalog = make_catalog(restaurant_packet(), visit_packet())
    gaps, composition = connect(result, catalog)
    final = workspace(composition, catalog)
    assert gaps[0].latest_arrival_time - gaps[0].departure_time == timedelta(minutes=5)
    assert final.itinerary.visit_stops[0].planned_start == datetime.fromisoformat(
        "2026-10-10T09:05:00+09:00"
    )


def test_mixed_timezone_schedule_is_correctable_validation_error():
    placement = meal_placement()
    placement["planned_end"] = "2026-10-10T09:00:00"
    with pytest.raises(ValueError, match="timezone|UTC offset"):
        ItineraryCompositionDraft.model_validate(itinerary_draft([placement]))


def test_revision_prompt_contains_existing_daily_draft_and_current_problem():
    original = make_planning_state().model_copy(
        update={
            "placement_skeleton": ItineraryCompositionDraft.model_validate(itinerary_draft()),
            "composition_failure_context": "rest overlaps train",
        }
    )
    prompt = _build_composition_prompt(original, "repair rest", skeleton_only=True)
    assert "rest overlaps train" in prompt.runtime
    assert "candidate_dining" in prompt.runtime
    assert "2026-10-10T08:00:00+09:00" in prompt.runtime


def test_composition_phase_selects_draft_or_materialization():
    empty = make_planning_state()
    assert _composition_phase(empty) == "placement_skeleton"
    drafted = empty.model_copy(
        update={
            "placement_skeleton": ItineraryCompositionDraft.model_validate(
                itinerary_draft()
            )
        }
    )
    assert _composition_phase(drafted) == "materialize_connectors"


@pytest.mark.parametrize("provider", [False, True])
def test_occurrences_reach_connectors_workspace_and_checkpoint(provider):
    routes = (
        [
            make_local_transport_packet(
                "candidate_to_museum",
                origin_place_id="place_candidate_dining",
                destination_place_id="place_candidate_visit",
            ),
            make_local_transport_packet(
                "candidate_to_cafe",
                origin_place_id="place_candidate_visit",
                destination_place_id="place_candidate_dining",
            ),
        ]
        if provider
        else []
    )
    catalog = make_catalog(restaurant_packet(), visit_packet(), *routes)
    payload = itinerary_draft(
        [
            meal_placement(),
            visit_entry(),
            meal_placement("lunch", "12:00", "13:00"),
            visit_entry("14:00", "15:00"),
            meal_placement("dinner", "18:00", "19:00"),
        ]
    )
    payload["days"].append(
        {
            **payload["days"][0],
            "day_id": "day_2",
            "day": 2,
            "date": "2026-10-11",
            "placements": [meal_placement(day="2026-10-11")],
        }
    )
    payload["duration_days"] = 2
    skeleton = parse_itinerary_composition(json.dumps(payload))
    before = skeleton.model_dump()
    gaps, composition = connect(skeleton, catalog)
    assert len({gap.gap_id for gap in gaps}) == 4
    assert gaps[0].from_entry_key != gaps[2].from_entry_key
    assert [gap.from_entry_key for gap in gaps] == [
        placement_occurrence_key("day_1", item)
        for item in skeleton.days[0].placements[:-1]
    ]
    result = workspace(composition, catalog)
    restored = restore_planning_state(
        make_planning_state(),
        recommendation_catalog=result.recommendation_catalog,
        placement_skeleton=skeleton,
        trip_workspace_v2=result,
    )
    assert (
        len(
            {item.item_id for item in restored.trip_workspace_v2.itinerary.dining_stops}
        )
        == 4
    )
    assert len(result.itinerary.visit_stops) == 2
    assert len(result.itinerary.transport_legs) == 4
    assert len(result.selection_slots) == (10 if provider else 6)
    assert skeleton.model_dump() == before


@pytest.mark.parametrize("stops", [[], [visit_entry()]])
def test_pure_transport_station_change_and_local_stops(stops):
    inbound = long_distance_packet(
        "candidate_in",
        "home",
        "east",
        "2026-10-10T07:00:00+09:00",
        "2026-10-10T09:00:00+09:00",
        "a" * 64,
    )
    outbound = long_distance_packet(
        "candidate_out",
        "west",
        "home",
        "2026-10-10T17:00:00+09:00",
        "2026-10-10T19:00:00+09:00",
        "b" * 64,
    )
    catalog = make_catalog(inbound, outbound, visit_packet())
    skeleton = parse_itinerary_composition(
        json.dumps(
            itinerary_draft(
                [transport("candidate_in"), *stops, transport("candidate_out")]
            )
        )
    )
    gaps, composition = connect(skeleton, catalog)
    result = workspace(composition, catalog)
    assert len(result.itinerary.visit_stops) == len(stops)
    assert (
        len(
            [
                leg
                for leg in result.itinerary.transport_legs
                if leg.transport_class == "long_distance"
            ]
        )
        == 2
    )
    assert gaps


@pytest.mark.asyncio
async def test_revision_model_receives_distinct_actual_drafts(monkeypatch):

    catalog = make_catalog(restaurant_packet())
    seen = []

    class Model:
        async def ainvoke(self, messages, **kwargs):
            seen.append(messages[-1]["content"])
            return json.dumps(itinerary_draft())

    for label in ("旧稿甲", "旧稿乙"):
        payload = itinerary_draft()
        payload["title"] = label
        current = restore_planning_state(
            make_planning_state(),
            recommendation_catalog=catalog,
            placement_skeleton=ItineraryCompositionDraft.model_validate(payload),
            composition_failure_context="rest conflict",
        )
        await composition._compose_draft(current, "revise", Model())
    assert seen[0] != seen[1]
    assert "旧稿甲" in seen[0] and "旧稿乙" in seen[1]


@pytest.mark.asyncio
async def test_structure_retry_keeps_new_reason_and_resolves_authored_place(
    monkeypatch,
):
    from travel_agent.planning.itinerary.draft import authored_places

    entry = visit_entry()
    entry.pop("candidate_id")
    entry["authored_place"] = {
        "name": "English Museum",
        "local_name": "Museum",
        "city": "Tokyo",
        "address": "1 Museum Street",
        "selection_reason": "建筑与摄影需求",
        "visit_type": "culture",
        "highlights": ["建筑空间"],
    }
    payload = itinerary_draft([entry, meal_placement("dinner", "18:00", "19:00")])
    payload["days"][0]["placements"][1].update(
        planned_start="2026-10-10T11:00:00+09:00",
        planned_end="2026-10-10T12:01:00+09:00",
    )
    previous = ItineraryCompositionDraft.model_validate(payload)
    current = restore_planning_state(
        make_planning_state(),
        recommendation_catalog=make_catalog(restaurant_packet()),
        placement_skeleton=previous,
    )
    calls = []

    async def resolve(**kwargs):
        calls.append(kwargs["name"])
        return {
            "name": "美術館",
            "place_id": "located_museum",
            "address": "1 Museum Street",
            "latitude": 35.6,
            "longitude": 139.7,
        }

    monkeypatch.setattr(locations, "resolve_authored_place", resolve)
    monkeypatch.setattr(locations, "_authored_place_tool_access", lambda state: None)

    class Model:
        def __init__(self):
            self.messages = []

        async def ainvoke(self, messages, **kwargs):
            self.messages.append(list(messages))
            response = json.loads(json.dumps(payload))
            if len(self.messages) == 1:
                response["days"][0]["placements"][1]["planned_start"] = None
            else:
                assert "does not match the required structure" in messages[-1]["content"]
                response["days"][0]["placements"][0]["authored_place"][
                    "selection_reason"
                ] = "新的推荐理由"
            return json.dumps(response)

    model = Model()
    result = await composition._compose_draft(current, "revise", model)
    place = authored_places(result)[0].place
    assert len(model.messages) == 2 and calls == ["English Museum"]
    assert place.resolved_place_id == "located_museum"
    assert place.name == "English Museum"
    assert place.selection_reason == "新的推荐理由"


def test_overnight_display_reuses_one_billed_transport_entity():
    packet = long_distance_packet(
        "candidate_night",
        "home",
        "east",
        "2026-10-10T23:00:00+09:00",
        "2026-10-11T05:00:00+09:00",
        "a" * 64,
    )
    catalog = make_catalog(packet)
    payload = itinerary_draft([transport("candidate_night")])
    payload["days"].append(
        {**payload["days"][0], "day_id": "day_2", "day": 2, "date": "2026-10-11"}
    )
    payload["duration_days"] = 2
    skeleton = parse_itinerary_composition(json.dumps(payload))
    _, composition = connect(skeleton, catalog)
    result = workspace(composition, catalog)
    assert len(result.itinerary.transport_legs) == 1
    refs = [ref for day in result.itinerary.day_plans for ref in day.timeline]
    assert [ref.projection_role for ref in refs] == ["departure", "arrival"]
    assert len({ref.entity_id for ref in refs}) == 1
    assert len(result.selection_slots) == 1
    restore_planning_state(make_planning_state(), trip_workspace_v2=result)


def test_lodging_morning_and_evening_are_distinct_occurrences():
    from travel_agent.planning.research.candidates import LodgingCandidate

    packet = visit_packet("candidate_hotel")
    original = packet.candidates[0].model_dump()
    data = {
        key: value
        for key, value in original.items()
        if key in LodgingCandidate.model_fields
    }
    data.update(
        candidate_kind="lodging",
        property_name="Hotel",
        check_in_date="2026-10-10",
        check_out_date="2026-10-12",
        nights=2,
        provider_place_type="hotel",
        availability_status="needs_confirmation",
    )
    payload = packet.model_dump()
    payload.update(
        worker_kind="accommodation_researcher",
        candidates=[LodgingCandidate.model_validate(data).model_dump()],
    )
    catalog = make_catalog(restaurant_packet(), ResearchPacket.model_validate(payload))
    payload = itinerary_draft([meal_placement("lunch", "12:00", "13:00")])
    payload.update(duration_days=3, lodging_candidate_ids=["candidate_hotel"])
    for day in (2, 3):
        local_date = f"2026-10-{day + 9}"
        payload["days"].append(
            {
                **payload["days"][0],
                "day_id": f"day_{day}",
                "day": day,
                "date": local_date,
                "placements": [meal_placement("lunch", "12:00", "13:00", local_date)],
            }
        )
    skeleton = parse_itinerary_composition(json.dumps(payload))
    gaps, composition = connect(skeleton, catalog)
    middle = [gap for gap in gaps if gap.day_id == "day_2"]
    assert len(middle) == 2
    assert middle[0].from_entry_key != middle[1].to_entry_key
    result = workspace(composition, catalog)
    assert len(result.itinerary.transport_legs) == 4
    assert len(result.itinerary.lodging_stays) == 1
    restore_planning_state(make_planning_state(), placement_skeleton=skeleton, trip_workspace_v2=result)


@pytest.mark.asyncio
async def test_changed_authored_identity_resolves_again_and_internal_parse_keeps_trusted_location(monkeypatch):
    from travel_agent.planning.itinerary.draft import authored_places

    entry = visit_entry()
    entry.pop("candidate_id")
    entry["authored_place"] = {
        "name": "Museum A", "local_name": "Museum A", "city": "Tokyo", "address": "Address A",
        "highlights": ["Museum collection"],
        "selection_reason": "原位置", "visit_type": "culture",
        "resolved_place_id": "trusted_a", "resolved_address": "Provider A",
        "resolved_latitude": 35.6, "resolved_longitude": 139.7,
    }
    previous = parse_itinerary_composition(json.dumps(itinerary_draft([entry])))
    restored = restore_planning_state(make_planning_state(), placement_skeleton=previous)
    assert authored_places(restored.placement_skeleton)[0].place.resolved_place_id == "trusted_a"
    response = previous.model_dump(mode="json")
    place = response["days"][0]["placements"][0]["authored_place"]
    place.update(name="Museum B", local_name="Museum B", address="Address B", selection_reason="新位置")
    calls = []
    async def resolve(**kwargs):
        calls.append(kwargs["name"])
        return {"name": "Museum B", "place_id": "trusted_b", "address": "Provider B", "latitude": 35.7, "longitude": 139.8}
    monkeypatch.setattr(locations, "resolve_authored_place", resolve)
    monkeypatch.setattr(locations, "_authored_place_tool_access", lambda state: None)
    class Model:
        async def ainvoke(self, messages, **kwargs):
            return json.dumps(response)
    current = restore_planning_state(restored, recommendation_catalog=make_catalog())
    result = await composition._compose_draft(current, "revise", Model())
    located = authored_places(result)[0].place
    assert calls == ["Museum B"]
    assert located.resolved_place_id == "trusted_b" and located.resolved_latitude == 35.7
    assert located.selection_reason == "新位置"


@pytest.mark.asyncio
async def test_unlocated_authored_entry_is_kept_without_coordinates(monkeypatch):
    entry = visit_entry()
    entry.pop("candidate_id")
    entry["authored_place"] = {
        "name": "Unknown Museum",
        "local_name": "Unknown Museum",
        "city": "Tokyo",
        "address": "1 Unknown Street",
        "selection_reason": "建筑与摄影需求",
        "visit_type": "culture",
        "highlights": ["建筑空间"],
    }

    async def resolve(**kwargs):
        return None

    monkeypatch.setattr(locations, "resolve_authored_place", resolve)
    monkeypatch.setattr(locations, "_authored_place_tool_access", lambda state: None)

    catalog = make_catalog(restaurant_packet())
    current = restore_planning_state(
        make_planning_state(), recommendation_catalog=catalog
    )

    class Model:
        async def ainvoke(self, messages, **kwargs):
            return json.dumps(
                itinerary_draft([entry, meal_placement("dinner", "18:00", "19:00")])
            )

    draft = await composition._compose_draft(current, "compose", Model())
    gaps, connected = connect(draft, catalog)
    result = workspace(connected, catalog)
    stop = result.itinerary.visit_stops[0]
    assert stop.name == "Unknown Museum"
    assert stop.place_id == "authored:Tokyo:Unknown Museum"
    assert stop.latitude is None and stop.longitude is None
    assert len(gaps) == 1


@pytest.mark.asyncio
async def test_unlocated_authored_visit_uses_candidate_entity_and_keeps_schedule(
    monkeypatch,
):
    selected = with_provider_coordinates(
        visit_packet("candidate_b"),
        name="Tokyo National Museum",
        address="13-9 Uenokoen",
        selection_reasons=["候选自身的建筑价值"],
        highlights=["候选馆藏"],
    )
    catalog = make_catalog(
        visit_packet("candidate_a_without_coordinates"),
        selected,
    )
    entry = authored_visit()

    async def resolve(**kwargs):
        return None

    monkeypatch.setattr(locations, "resolve_authored_place", resolve)
    monkeypatch.setattr(locations, "_authored_place_tool_access", lambda state: None)

    class Model:
        async def ainvoke(self, messages, **kwargs):
            return json.dumps(itinerary_draft([entry]))

    current = restore_planning_state(
        make_planning_state(), recommendation_catalog=catalog
    )
    result = await composition._compose_draft(current, "compose", Model())
    placement = result.days[0].placements[0]
    assert placement.candidate_id == "candidate_b"
    assert placement.authored_place is None
    assert placement.planned_start == datetime.fromisoformat(entry["planned_start"])
    assert placement.planned_end == datetime.fromisoformat(entry["planned_end"])
    assert placement.duration_minutes == entry["duration_minutes"]
    assert placement.selection_reason is None

    stop = workspace(result, catalog).itinerary.visit_stops[0]
    assert stop.name == "Tokyo National Museum"
    assert stop.address == "13-9 Uenokoen"
    assert stop.selection_reason == "候选自身的建筑价值"
    assert stop.visit_highlights == ["候选馆藏"]


def test_unlocated_authored_dining_keeps_meal_type_and_schedule():
    catalog = make_catalog(
        with_provider_coordinates(
            restaurant_packet("candidate_a_breakfast"),
            branch_name="Breakfast Cafe",
            meal_types=["breakfast"],
        ),
        with_provider_coordinates(
            restaurant_packet(),
            branch_name="Sushi Tokyo",
            selection_reasons=["候选自身的菜品理由"],
            cuisine_types=["寿司"],
            recommended_dishes=["海胆"],
        ),
    )
    draft = parse_itinerary_composition(
        json.dumps(itinerary_draft([authored_dining()]))
    )
    original = draft.days[0].placements[0]

    result = locations.replace_unlocated_authored_places(draft, catalog)
    placement = result.days[0].placements[0]
    assert placement.candidate_id == "candidate_dining"
    assert placement.authored_place is None
    for field in ("planned_start", "planned_end", "duration_minutes", "meal_type"):
        assert getattr(placement, field) == getattr(original, field)

    stop = workspace(result, catalog).itinerary.dining_stops[0]
    assert stop.name == "Sushi Tokyo"
    assert stop.meal_type == "dinner"
    assert stop.selection_reason == "候选自身的菜品理由"
    assert stop.cuisine_types == ["寿司"]
    assert stop.recommended_dishes == ["海胆"]


def test_authored_fallback_does_not_cross_destination_or_kind():
    catalog = make_catalog(
        with_provider_coordinates(
            visit_packet("candidate_other_destination"),
            destination_id="destination_kyoto",
        ),
        with_provider_coordinates(restaurant_packet()),
    )
    draft = parse_itinerary_composition(
        json.dumps(itinerary_draft([authored_visit()]))
    )

    result = locations.replace_unlocated_authored_places(draft, catalog)

    assert result == draft


def test_unlocated_authored_entry_is_kept_when_candidate_has_no_matching_coordinates():
    packet = visit_packet("candidate_visit")
    source = packet.source_records[0].model_copy(
        update={
            "snapshot": {
                "results": [
                    {
                        "place_id": "another_place",
                        "latitude": 35.6,
                        "longitude": 139.7,
                    }
                ]
            }
        }
    )
    catalog = make_catalog(packet.model_copy(update={"source_records": [source]}))
    draft = parse_itinerary_composition(
        json.dumps(itinerary_draft([authored_visit()]))
    )

    result = locations.replace_unlocated_authored_places(draft, catalog)

    assert result == draft
    place = result.days[0].placements[0].authored_place
    assert place.name == "Museum district"
    assert place.resolved_place_id is None
    assert place.resolved_latitude is None and place.resolved_longitude is None


def test_located_authored_entry_is_not_replaced_by_candidate():
    entry = authored_visit("Located Museum")
    entry["authored_place"].update(
        resolved_place_id="provider_located_museum",
        resolved_address="Provider address",
        resolved_latitude=35.7,
        resolved_longitude=139.8,
    )
    draft = parse_itinerary_composition(json.dumps(itinerary_draft([entry])))
    catalog = make_catalog(with_provider_coordinates(visit_packet("candidate_visit")))

    result = locations.replace_unlocated_authored_places(draft, catalog)

    assert result == draft
    placement = result.days[0].placements[0]
    assert placement.candidate_id is None
    assert placement.authored_place.resolved_place_id == "provider_located_museum"


def test_authored_fallback_uses_each_unused_candidate_once_in_stable_order():
    already_used = visit_entry("08:00", "09:00")
    already_used["candidate_id"] = "candidate_b"
    draft = parse_itinerary_composition(
        json.dumps(
            itinerary_draft(
                [
                    already_used,
                    authored_visit("Generic Museum One", "10:00", "11:00"),
                    authored_visit("Generic Museum Two", "12:00", "13:00"),
                ]
            )
        )
    )
    catalog = make_catalog(
        with_provider_coordinates(visit_packet("candidate_c")),
        with_provider_coordinates(visit_packet("candidate_b")),
        with_provider_coordinates(visit_packet("candidate_a")),
    )

    result = locations.replace_unlocated_authored_places(draft, catalog)

    assert [
        placement.candidate_id for placement in result.days[0].placements
    ] == ["candidate_b", "candidate_a", "candidate_c"]


def route_packet(candidate_id="candidate_slow", duration=60, **updates):
    packet = make_local_transport_packet(
        candidate_id,
        origin_place_id="place_candidate_dining",
        destination_place_id="place_candidate_visit",
    )
    payload = packet.model_dump()
    payload["candidates"][0].update(duration_minutes=duration, **updates)
    segment = payload["candidates"][0]["segments"][0]
    segment["duration_minutes"] = duration
    for field in ("from_endpoint", "to_endpoint"):
        if field in updates:
            segment[field] = updates[field]
    return ResearchPacket.model_validate(payload)


@pytest.mark.parametrize("scheduled", [False, True])
def test_matching_provider_route_fills_gap_without_quality_filter(scheduled):
    from travel_agent.planning.itinerary.connectors import unfilled_connector_gaps

    timing = {
        "departure_at": "2026-10-10T09:00:00+09:00",
        "arrival_at": "2026-10-10T10:00:00+09:00",
    } if scheduled else {}
    catalog = make_catalog(restaurant_packet(), visit_packet(), route_packet(**timing))
    skeleton = parse_itinerary_composition(
        json.dumps(itinerary_draft([meal_placement(), visit_entry("09:10", "10:10")]))
    )
    gaps = extract_local_connector_gaps(skeleton, catalog, weather_data_revision=0)
    assert unfilled_connector_gaps(catalog, gaps) == []
    result = materialize_skeleton_connectors(skeleton, catalog, gaps, {})
    assert result.days[0].placements[1].candidate_id == "candidate_slow"


def test_route_with_other_endpoint_is_not_used_for_the_gap():
    from travel_agent.planning.itinerary.connectors import unfilled_connector_gaps

    catalog = make_catalog(
        restaurant_packet(),
        visit_packet(),
        route_packet(from_endpoint={"name": "Other", "place_id": "other"}),
    )
    skeleton = parse_itinerary_composition(
        json.dumps(itinerary_draft([meal_placement(), visit_entry("09:10", "10:10")]))
    )
    gaps = extract_local_connector_gaps(skeleton, catalog, weather_data_revision=0)
    assert unfilled_connector_gaps(catalog, gaps) == gaps
    _, composition = connect(skeleton, catalog)
    assert composition.days[0].placements[1].authored_route.duration_minutes == 2


@pytest.mark.asyncio
async def test_fastest_provider_alternative_is_selected(monkeypatch):
    from travel_agent.planning.itinerary import node

    catalog = make_catalog(
        restaurant_packet(), visit_packet(),
        route_packet(),
        route_packet("candidate_fast", 5,
                     departure_at="2026-10-10T09:00:00+09:00",
                     arrival_at="2026-10-10T09:05:00+09:00"),
    )
    skeleton = parse_itinerary_composition(json.dumps(
        itinerary_draft([meal_placement(), visit_entry("09:10", "10:10")])
    ))
    current = restore_planning_state(
        make_planning_state(), recommendation_catalog=catalog,
        placement_skeleton=skeleton,
        execution_plan=[["itinerary_planner"]], agent_status={"itinerary_planner": "pending"},
    )

    def no_model(*args, **kwargs):
        pytest.fail("provider alternatives must not invoke a model")

    async def no_authoring(*args, **kwargs):
        pytest.fail("provider alternatives must not be replaced by authored routes")

    monkeypatch.setattr(node, "get_model_router", no_model)
    monkeypatch.setattr(node, "llm_for_task", no_model)
    monkeypatch.setattr(node, "_author_connector_routes", no_authoring)
    completed = restore_planning_state(current, **await node.itinerary_planner_node(current, {}))
    assert completed.agent_status["itinerary_planner"] == "completed"
    assert completed.composition_failure_context is None
    result = completed.trip_workspace_v2
    itinerary = result.itinerary
    assert len(itinerary.transport_legs) == 1
    assert itinerary.transport_legs[0].lineage.candidate_id == "candidate_fast"
    assert itinerary.transport_legs[0].duration_minutes == 5
    for stop, placement in (
        (itinerary.dining_stops[0], skeleton.days[0].placements[0]),
        (itinerary.visit_stops[0], skeleton.days[0].placements[1]),
    ):
        assert stop.lineage.candidate_id == placement.candidate_id
        assert stop.planned_start == placement.planned_start
        assert stop.planned_end == placement.planned_end
    assert len(result.selection_slots) == 3
    restore_planning_state(completed, trip_workspace_v2=result)


@pytest.mark.asyncio
async def test_provider_route_beyond_the_remaining_window_is_still_used(monkeypatch):
    from travel_agent.planning.itinerary import node

    catalog = make_catalog(restaurant_packet(), visit_packet(), route_packet())
    skeleton = parse_itinerary_composition(
        json.dumps(itinerary_draft([meal_placement(), visit_entry("09:10", "10:10")]))
    )
    current = restore_planning_state(
        make_planning_state(),
        recommendation_catalog=catalog,
        placement_skeleton=skeleton,
        execution_plan=[["itinerary_planner"]],
        agent_status={"itinerary_planner": "pending"},
    )

    async def no_authoring(*args, **kwargs):
        pytest.fail("matching provider route must be used")

    monkeypatch.setattr(node, "_author_connector_routes", no_authoring)
    completed = restore_planning_state(
        current, **await node.itinerary_planner_node(current, {})
    )
    assert completed.agent_status["itinerary_planner"] == "completed"
    legs = completed.trip_workspace_v2.itinerary.transport_legs
    assert len(legs) == 1
    assert legs[0].lineage.candidate_id == "candidate_slow"


@pytest.mark.asyncio
async def test_materialize_failure_returns_failed_status_and_bounded_context(monkeypatch):
    from travel_agent.planning.itinerary import node

    catalog = make_catalog(restaurant_packet(), visit_packet(), route_packet())
    skeleton = parse_itinerary_composition(
        json.dumps(itinerary_draft([meal_placement(), visit_entry("09:10", "10:10")]))
    )
    current = restore_planning_state(
        make_planning_state(),
        recommendation_catalog=catalog,
        placement_skeleton=skeleton,
        execution_plan=[["itinerary_planner"]],
        agent_status={"itinerary_planner": "pending"},
    )

    def fail_materialize(**kwargs):
        raise ValueError("物化失败 " + "细节" * 500)

    monkeypatch.setattr(node, "materialize_trip_workspace", fail_materialize)
    failed = restore_planning_state(
        current, **await node.itinerary_planner_node(current, {})
    )
    assert failed.agent_status["itinerary_planner"] == "failed"
    assert "物化失败" in failed.last_error
    assert failed.composition_failure_context.startswith(
        "materialize_connectors/workspace_materialization 阶段失败"
    )
    assert len(failed.composition_failure_context) <= 600
    assert failed.trip_workspace_v2 is None


@pytest.mark.asyncio
async def test_connector_estimator_receives_real_names_and_uses_full_estimate():

    catalog = make_catalog(restaurant_packet(), visit_packet())
    skeleton = parse_itinerary_composition(
        json.dumps(itinerary_draft([meal_placement(), visit_entry("09:10", "10:10")]))
    )
    gaps = extract_local_connector_gaps(skeleton, catalog, weather_data_revision=0)

    class Model:
        async def ainvoke(self, messages, **kwargs):
            described = json.loads(messages[-1]["content"].split("：", 1)[1])[0]
            assert described["from_endpoint"]["name"] == "Cafe"
            assert described["to_endpoint"]["name"] == "candidate_visit"
            return json.dumps({"connectors": [{"gap_id": gaps[0].gap_id, "mode": "bus", "duration_minutes": 60, "selection_reason": "honest estimate"}]})

    authored = await connector_estimates._author_connector_routes(Model(), gaps)
    result = materialize_skeleton_connectors(skeleton, catalog, gaps, authored)
    assert result.days[0].placements[1].authored_route.duration_minutes == 60


@pytest.mark.parametrize("partial", [False, True])
def test_candidate_scoped_mode_lock_targets_actual_occurrences_only(partial):
    from travel_agent.planning.itinerary.connectors import (
        connector_mode_requests_from_constraint_pack,
    )

    catalog = make_catalog(restaurant_packet(), visit_packet())
    payload = itinerary_draft([meal_placement(), visit_entry(), meal_placement("lunch", "12:00", "13:00"), visit_entry("14:00", "15:00")])
    next_day = json.loads(json.dumps(payload["days"][0]))
    next_day.update(day_id="day_2", day=2, date="2026-10-11")
    for placement in next_day["placements"]:
        for field in ("planned_start", "planned_end"):
            placement[field] = placement[field].replace("2026-10-10", "2026-10-11")
    payload["days"].append(next_day)
    payload["duration_days"] = 2
    skeleton = parse_itinerary_composition(json.dumps(payload))
    params = {"from_candidate_id": "candidate_dining", "locked_local_mode": "taxi"}
    if not partial:
        params["to_candidate_id"] = "candidate_visit"
    pack = {"hard_constraints": [{"status": "active", "visibility": "user_visible", "category": "transport_constraint", "source_refs": [{"source": "current_query"}], "params": params}]}
    requested, required = connector_mode_requests_from_constraint_pack(skeleton, pack, catalog)
    expected = set() if partial else {
        (placement_occurrence_key(day.day_id, day.placements[index]),
         placement_occurrence_key(day.day_id, day.placements[index + 1]))
        for day in skeleton.days for index in (0, 2)
    }
    assert required == expected
    assert requested == {pair: ["taxi"] for pair in expected}
    gaps = extract_local_connector_gaps(
        skeleton, catalog, weather_data_revision=0,
        flexible_mode_requests=requested, required_flexible_mode_pairs=required,
    )
    assert sum(gap.allowed_transport_classes == ["flexible"] for gap in gaps) == len(expected)


@pytest.mark.parametrize("meal_type", ["snack", "lunch"])
def test_multiple_same_meal_occurrences_have_distinct_targeted_slots_after_checkpoint(meal_type):
    packets = []
    for candidate_id in ("cafe_first", "cafe_second"):
        packet = visit_packet(candidate_id)
        data = {key: value for key, value in packet.candidates[0].model_dump().items() if key in DiningCandidate.model_fields}
        data.update(candidate_kind="dining", branch_name=candidate_id, meal_types=[meal_type], availability_status="needs_confirmation", provider_place_type="restaurant")
        payload = packet.model_dump()
        payload["candidates"] = [DiningCandidate.model_validate(data).model_dump()]
        packets.append(ResearchPacket.model_validate(payload))
    first = {**meal_placement(meal_type, "11:00", "12:00"), "candidate_id": "cafe_first"}
    second = {**meal_placement(meal_type, "13:00", "14:00"), "candidate_id": "cafe_second"}
    catalog = make_catalog(*packets)
    skeleton = parse_itinerary_composition(json.dumps(itinerary_draft([first, second])))
    _, composition = connect(skeleton, catalog)
    result = workspace(composition, catalog)
    restored = restore_planning_state(make_planning_state(), trip_workspace_v2=result, recommendation_catalog=result.recommendation_catalog)
    result = restored.trip_workspace_v2
    assert len(result.selection_slots) == len(result.itinerary.dining_stops) == 2
    assert len({slot.selection_slot_id for slot in result.selection_slots}) == 2
    for stop in result.itinerary.dining_stops:
        slot = next(slot for slot in result.selection_slots if slot.selection_slot_id == stop.lineage.selection_slot_id)
        selected = next(option for option in slot.options if option.option_id == slot.selected_option_id)
        assert selected.candidate_entity_ref.entity_id == stop.item_id
        assert selected.candidate_id == stop.lineage.candidate_id


def test_real_duplicate_occurrence_and_overlapping_repeat_still_fail():
    with pytest.raises(ValueError, match="duplicate|more than once"):
        parse_itinerary_composition(json.dumps(itinerary_draft([visit_entry(), visit_entry()])))
    with pytest.raises(ValueError, match="overlap"):
        parse_itinerary_composition(json.dumps(itinerary_draft([visit_entry(), visit_entry("10:30", "11:30")])))
    catalog = make_catalog(restaurant_packet())
    skeleton = parse_itinerary_composition(json.dumps(itinerary_draft()))
    result = workspace(skeleton, catalog)
    payload = result.model_dump()
    payload["itinerary"].pop("cost_summary")
    payload["itinerary"]["dining_stops"].append(payload["itinerary"]["dining_stops"][0])
    with pytest.raises(ValueError, match="dining stop ids must be unique"):
        restore_planning_state(make_planning_state(), trip_workspace_v2=payload)
