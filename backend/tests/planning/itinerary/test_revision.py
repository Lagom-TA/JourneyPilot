
import json
from datetime import date, datetime, timedelta

import pytest

import travel_agent.planning.research.dispatch as planning_research_dispatch
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
from travel_agent.planning.itinerary.checks import (
    validate_itinerary_transport_topology,
    validate_placement_skeleton,
)
from travel_agent.planning.itinerary.connectors import (
    extract_local_connector_gaps,
    materialize_skeleton_connectors,
)
from travel_agent.planning.itinerary.draft import (
    AuthoredRoute,
    ItineraryCompositionDraft,
    ItineraryCompositionError,
    placement_occurrence_key,
)
from travel_agent.planning.itinerary.materialize import materialize_trip_workspace
from travel_agent.planning.itinerary.node import _composition_phase
from travel_agent.planning.itinerary.parsing import parse_itinerary_composition
from travel_agent.planning.itinerary.prompts import _build_composition_prompt
from travel_agent.planning.requirements.snapshot_contracts import IntentContractSnapshot
from travel_agent.planning.research import evaluation as candidate_evaluation
from travel_agent.planning.research.candidates import DiningCandidate
from travel_agent.planning.research.discovery_contracts import CandidateDiscoveryOrigin
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.planning.research.ranking import rank_candidates
from travel_agent.planning.research.selection_policy import (
    build_candidate_selection_plan,
)


def visit_packet(candidate_id="candidate_visit"):
    return make_visit_packet(
        candidate_id,
        candidate_id,
        origin=CandidateDiscoveryOrigin.INTENT_QUERY,
        query_id=f"query_{candidate_id}",
        intent_id="intent_test",
    )


def restaurant_packet():
    packet = visit_packet("candidate_dining")
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


def workspace(composition, catalog, *, intent_spec=None, **requirements):
    spec = intent_spec or make_planning_state().intent_spec
    selection = build_candidate_selection_plan(
        catalog=catalog,
        intent_spec=spec,
        ranking_scores=rank_candidates(catalog=catalog, intent_spec=spec, matches=[]),
        duration_days=composition.duration_days,
        destination_count=1,
    )
    return materialize_trip_workspace(
        run_id="run_test",
        workspace_revision=0,
        composition=composition,
        catalog=catalog,
        intent_contract_snapshot=IntentContractSnapshot.from_intent_spec(spec),
        candidate_selection_plan=selection,
        composition_mutations=[],
        **requirements,
    )


def connect(skeleton, catalog, **requirements):
    gaps = extract_local_connector_gaps(
        skeleton, catalog, weather_data_revision=0, **requirements
    )
    routes = {
        gap.gap_id: AuthoredRoute(
            mode="bus", duration_minutes=2, selection_reason="相邻地点短途公交"
        )
        for gap in gaps
    }
    result = materialize_skeleton_connectors(
        skeleton, catalog, gaps, routes, **requirements
    )
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
    scores = rank_candidates(catalog=catalog, intent_spec=original.intent_spec, matches=[])
    catalog = catalog.model_copy(update={"candidate_ranking_scores": scores})
    selection = build_candidate_selection_plan(
        catalog=catalog, intent_spec=original.intent_spec, ranking_scores=scores,
        duration_days=payload["duration_days"], destination_count=1,
    )
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
    current = restore_planning_state(
        original, recommendation_catalog=catalog, candidate_selection_plan=selection,
    )
    drafted = restore_planning_state(current, **await node.itinerary_planner_node(current, {}))
    assert drafted.composition_failure_context is None
    assert len(calls) == 1
    ready = restore_planning_state(drafted, candidate_gate_status="passed")
    completed = restore_planning_state(ready, **await node.itinerary_planner_node(ready, {}))
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
    repeated = restore_planning_state(ready, **await node.itinerary_planner_node(ready, {}))
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


def test_failed_materialization_returns_to_draft_revision():
    current = make_planning_state().model_copy(
        update={
            "placement_skeleton": ItineraryCompositionDraft.model_validate(itinerary_draft()),
            "composition_failure_context": "rest overlaps train",
        }
    )
    assert _composition_phase(current) == "placement_skeleton"


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
        candidate_selection_plan=result.candidate_selection_plan,
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


@pytest.mark.parametrize("scoped", [False, True])
def test_pure_transport_station_change_and_return_requirements(scoped):
    from travel_agent.planning.research.provider_contracts import ProviderRouteLegScope

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
    legs = [
        ProviderRouteLegScope(
            leg_role="outbound",
            from_place_id="home",
            to_place_id="east",
            service_date=date(2026, 10, 10),
        ),
        ProviderRouteLegScope(
            leg_role="return",
            from_place_id="west",
            to_place_id="home",
            service_date=date(2026, 10, 10),
        ),
    ]
    requirements = {"required_long_distance_legs": legs}
    if scoped:
        requirements["required_leg_scope_ids"] = {
            "outbound@2026-10-10": "a" * 64,
            "return@2026-10-10": "b" * 64,
        }
    for stops in ([], [visit_entry()]):
        skeleton = parse_itinerary_composition(
            json.dumps(
                itinerary_draft([transport("candidate_in"), *stops, transport("candidate_out")])
            )
        )
        gaps, composition = connect(skeleton, catalog, **requirements)
        result = workspace(composition, catalog, **requirements)
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
        with pytest.raises(ItineraryCompositionError, match="connector"):
            validate_itinerary_transport_topology(skeleton, catalog, **requirements)
        missing = parse_itinerary_composition(
            json.dumps(itinerary_draft([transport("candidate_in")]))
        )
        for check in (
            validate_placement_skeleton,
            validate_itinerary_transport_topology,
        ):
            with pytest.raises(ItineraryCompositionError, match="return@2026-10-10"):
                check(missing, catalog, **requirements)
        with pytest.raises(ItineraryCompositionError, match="return@2026-10-10"):
            materialize_skeleton_connectors(missing, catalog, [], {}, **requirements)
        with pytest.raises(ItineraryCompositionError, match="return@2026-10-10"):
            workspace(missing, catalog, **requirements)
        assert gaps


@pytest.mark.asyncio
async def test_rest_conflict_routes_to_complete_revision_and_fresh_connectors(
    monkeypatch,
):
    from tests.fixtures.research_catalog import make_intent_spec, make_research_intent
    from travel_agent.planning.itinerary import node
    from travel_agent.planning.requirements.intent_contracts import (
        IntentKind,
        IntentTarget,
    )
    from travel_agent.planning.research import node as candidate_gate

    objective = make_research_intent("intent_trip", "Tokyo day trip", kind=IntentKind.OBJECTIVE)
    spec = make_intent_spec(objective.model_copy(update={"target": IntentTarget.TRIP, "impact_stages": ["composition"]}))
    original = make_planning_state()
    original = restore_planning_state(
        original, intent_spec=spec,
        planning_generation=original.planning_generation.model_copy(update={"intent_hash": spec.content_hash}),
        minimum_delivery_draft=original.minimum_delivery_draft.model_copy(update={"intent_spec_hash": spec.content_hash}),
    )
    catalog = make_catalog(visit_packet())
    catalog = catalog.model_copy(
        update={
            "candidate_ranking_scores": rank_candidates(
                catalog=catalog,
                intent_spec=spec,
                matches=[],
            )
        }
    )
    skeleton = parse_itinerary_composition(json.dumps(itinerary_draft([visit_entry()])))
    payload = skeleton.model_dump(mode="json")
    payload["days"][0]["day_design"] = {
        "focus": "休息",
        "rationale": "保留休息",
        "free_time": [
            {
                "planned_start": "2026-10-10T10:30:00+09:00",
                "planned_end": "2026-10-10T11:30:00+09:00",
            }
        ],
    }
    bad = ItineraryCompositionDraft.model_validate(payload)
    plan = build_candidate_selection_plan(
        catalog=catalog,
        intent_spec=spec,
        ranking_scores=rank_candidates(catalog=catalog, intent_spec=spec, matches=[]),
        duration_days=1,
        destination_count=1,
    )
    current = restore_planning_state(
        original,
        recommendation_catalog=catalog,
        candidate_selection_plan=plan,
        placement_skeleton=bad,
        candidate_gate_status="passed",
        execution_plan=[["itinerary_planner"]],
        agent_status={"itinerary_planner": "pending"},
    )
    failed = restore_planning_state(current, **await node.itinerary_planner_node(current, {}))
    assert "free time" in failed.composition_failure_context
    routed = restore_planning_state(failed, **await planning_research_dispatch.dispatcher_node(failed))
    assert planning_research_dispatch.route_after_dispatcher(routed) == "candidate_gate"
    repairing = restore_planning_state(routed, **await candidate_gate.candidate_gate_node(routed))
    assert candidate_gate.route_after_candidate_gate(repairing) == "composition_repair"
    assert repairing.composition_repair_attempts == 1
    fixed = json.loads(bad.model_dump_json())
    fixed["days"][0]["day_design"]["free_time"][0].update(
        planned_start="2026-10-10T11:00:00+09:00",
        planned_end="2026-10-10T12:00:00+09:00",
    )

    class Model:
        async def ainvoke(self, messages, **kwargs):
            assert "10:30:00" in messages[-1]["content"]
            return json.dumps(fixed)

    monkeypatch.setattr(node, "get_model_router", lambda: None)
    monkeypatch.setattr(node, "llm_for_task", lambda *args: Model())
    revised = restore_planning_state(repairing, **await node.itinerary_planner_node(repairing, {}))
    assert revised.trip_workspace_v2 is None and not revised.local_connector_gaps
    assert revised.intent_spec == repairing.intent_spec
    assert revised.recommendation_catalog == repairing.recommendation_catalog
    routed = restore_planning_state(revised, **await planning_research_dispatch.dispatcher_node(revised))
    assert planning_research_dispatch.route_after_dispatcher(routed) == "candidate_gate"
    monkeypatch.setattr(
        candidate_gate,
        "build_candidate_catalog",
        lambda state: (state.recommendation_catalog, [], []),
    )

    async def evaluate(**kwargs):
        return [], {}

    monkeypatch.setattr(candidate_evaluation, "evaluate_candidate_intents", evaluate)
    monkeypatch.setattr(candidate_evaluation, "get_model_router", lambda: None)
    monkeypatch.setattr(candidate_evaluation, "llm_for_task", lambda *args: None)
    ready = restore_planning_state(routed, **await candidate_gate.candidate_gate_node(routed))
    assert candidate_gate.route_after_candidate_gate(ready) == "passed"
    routed = restore_planning_state(ready, **await planning_research_dispatch.dispatcher_node(ready))
    assert planning_research_dispatch.route_after_dispatcher(routed) == "itinerary_planner"
    completed = restore_planning_state(routed, **await node.itinerary_planner_node(routed, {}))
    assert completed.agent_status["itinerary_planner"] == "completed"
    block = completed.trip_workspace_v2.itinerary.custom_blocks[0]
    assert block.planned_start.isoformat() == "2026-10-10T11:00:00+09:00"
    assert block.planned_end.isoformat() == "2026-10-10T12:00:00+09:00"


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
        await composition._compose_draft(current, "revise", Model(), set(), [], set())
    assert seen[0] != seen[1]
    assert "旧稿甲" in seen[0] and "旧稿乙" in seen[1]


@pytest.mark.asyncio
async def test_new_draft_researches_connectors_then_uses_the_same_materializer(
    monkeypatch,
):
    from tests.fixtures.research_catalog import make_research_brief
    from travel_agent.planning.itinerary import node
    from travel_agent.planning.research import node as candidate_gate
    from travel_agent.planning.research.query_planner import build_research_query_plan

    catalog = make_catalog(visit_packet(), restaurant_packet())
    skeleton = ItineraryCompositionDraft.model_validate(
        itinerary_draft([visit_entry(), meal_placement("dinner", "18:00", "19:00")])
    )
    current = make_planning_state()
    query_plan = build_research_query_plan(
        intent_spec=current.intent_spec, brief=make_research_brief(current.intent_spec)
    )
    current = restore_planning_state(
        current,
        placement_skeleton=skeleton,
        recommendation_catalog=catalog,
        research_query_plan=query_plan,
        execution_plan=[["itinerary_planner"]],
        agent_status={"itinerary_planner": "pending"},
        candidate_gate_status="needs_research",
    )
    monkeypatch.setattr(
        candidate_gate,
        "build_candidate_catalog",
        lambda state: (state.recommendation_catalog, [], []),
    )

    async def evaluate(**kwargs):
        return [], {}

    monkeypatch.setattr(candidate_evaluation, "evaluate_candidate_intents", evaluate)
    monkeypatch.setattr(candidate_evaluation, "get_model_router", lambda: None)
    monkeypatch.setattr(candidate_evaluation, "llm_for_task", lambda *args: None)
    pending = restore_planning_state(current, **await candidate_gate.candidate_gate_node(current))
    assert candidate_gate.route_after_candidate_gate(pending) == "transport_researcher"
    assert len(pending.local_connector_gaps) == 1
    gap = pending.local_connector_gaps[0]
    route_packet = make_local_transport_packet(
        "candidate_connection",
        origin_place_id=gap.from_place_id,
        destination_place_id=gap.to_place_id,
    )
    with_route = make_catalog(visit_packet(), restaurant_packet(), route_packet)
    pending = restore_planning_state(pending, recommendation_catalog=with_route)
    ready = restore_planning_state(pending, **await candidate_gate.candidate_gate_node(pending))
    assert candidate_gate.route_after_candidate_gate(ready) == "passed"
    routed = restore_planning_state(ready, **await planning_research_dispatch.dispatcher_node(ready))
    assert planning_research_dispatch.route_after_dispatcher(routed) == "itinerary_planner"
    completed = restore_planning_state(routed, **await node.itinerary_planner_node(routed, {}))
    assert completed.agent_status["itinerary_planner"] == "completed"
    assert (
        completed.trip_workspace_v2.itinerary.transport_legs[0].lineage.candidate_id
        == "candidate_connection"
    )


@pytest.mark.asyncio
async def test_located_retry_keeps_new_reasons_and_reuses_provider_identity(
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
        "resolved_place_id": "forged_but_valid",
        "resolved_address": "forged address",
        "resolved_latitude": 40.0,
        "resolved_longitude": 120.0,
    }
    payload = itinerary_draft([entry, meal_placement("dinner", "18:00", "19:00")])
    payload["days"][0]["placements"][1]["planned_start"] = "2026-10-10T11:00:00+09:00"
    payload["days"][0]["placements"][1]["planned_end"] = "2026-10-10T12:01:00+09:00"
    current = restore_planning_state(make_planning_state(), recommendation_catalog=make_catalog(restaurant_packet()))
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
            if len(self.messages) == 2:
                assistant = json.loads(messages[-2]["content"])
                assert (
                    assistant["days"][0]["placements"][0]["authored_place"][
                        "resolved_place_id"
                    ]
                    == "located_museum"
                )
                assert "positive transfer window" in messages[-1]["content"]
                response["days"][0]["placements"][0]["authored_place"][
                    "selection_reason"
                ] = "新的推荐理由"
                response["days"][0]["placements"][1].update(
                    planned_start="2026-10-10T12:00:00+09:00",
                    planned_end="2026-10-10T13:00:00+09:00",
                )
            return json.dumps(response)

    model = Model()
    result = await composition._compose_draft(current, "revise", model, set(), [], set())
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
async def test_existing_revision_budget_stops_reopening_the_broken_draft():

    from travel_agent.planning.itinerary.revision import (
        MAXIMUM_COMPOSITION_REPAIR_ATTEMPTS,
    )
    from travel_agent.planning.research import node as candidate_gate

    current = restore_planning_state(
        make_planning_state(),
        composition_repair_attempts=MAXIMUM_COMPOSITION_REPAIR_ATTEMPTS,
        composition_failure_context="rest overlaps activity",
        placement_skeleton=ItineraryCompositionDraft.model_validate(itinerary_draft()),
        candidate_gate_status="passed",
        execution_plan=[["itinerary_planner"]],
        agent_status={"itinerary_planner": "failed"},
    )
    routed = restore_planning_state(current, **await planning_research_dispatch.dispatcher_node(current))
    assert planning_research_dispatch.route_after_dispatcher(routed) == "to_check"
    exhausted = restore_planning_state(current, **await candidate_gate.candidate_gate_node(current))
    assert candidate_gate.route_after_candidate_gate(exhausted) == "passed"
    assert exhausted.composition_repair_attempts == MAXIMUM_COMPOSITION_REPAIR_ATTEMPTS


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
    result = await composition._compose_draft(current, "revise", Model(), set(), [], set())
    located = authored_places(result)[0].place
    assert calls == ["Museum B"]
    assert located.resolved_place_id == "trusted_b" and located.resolved_latitude == 35.7
    assert located.selection_reason == "新位置"


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
def test_known_provider_conflict_cannot_be_replaced_by_short_estimate(scheduled):
    from travel_agent.planning.itinerary.connectors import unfilled_connector_gaps

    timing = {
        "departure_at": "2026-10-10T09:00:00+09:00",
        "arrival_at": "2026-10-10T10:00:00+09:00",
    } if scheduled else {}
    catalog = make_catalog(restaurant_packet(), visit_packet(), route_packet(**timing))
    skeleton = parse_itinerary_composition(json.dumps(itinerary_draft([meal_placement(), visit_entry("09:10", "10:10")])))
    gaps = extract_local_connector_gaps(skeleton, catalog, weather_data_revision=0)
    for entry in (
        lambda: unfilled_connector_gaps(catalog, gaps),
        lambda: materialize_skeleton_connectors(
            skeleton, catalog, gaps,
            {gaps[0].gap_id: AuthoredRoute(mode="bus", duration_minutes=2, selection_reason="estimate")},
        ),
    ):
        with pytest.raises(ItineraryCompositionError, match="candidate_slow.*duration=60min"):
            entry()
    assert skeleton.days[0].placements[1].planned_start.hour == 9


@pytest.mark.parametrize("irrelevant", ["missing", "endpoint", "class", "destination", "date", "duration", "schedule"])
def test_only_same_scope_intrinsically_credible_route_is_conflict_evidence(irrelevant):
    from travel_agent.planning.itinerary.connectors import unfilled_connector_gaps

    changes = {
        "endpoint": {"from_endpoint": {"name": "Other", "place_id": "other"}},
        "class": {"transport_class": "flexible", "selected_mode": "taxi"},
        "destination": {"destination_id": "destination_elsewhere"},
        "date": {"departure_at": "2026-10-11T09:00:00+09:00", "arrival_at": "2026-10-11T10:00:00+09:00"},
        "duration": {"duration_minutes": 400},
        "schedule": {"departure_at": "2026-10-10T10:00:00+09:00", "arrival_at": "2026-10-10T09:00:00+09:00"},
    }
    updates = changes.get(irrelevant, {}).copy()
    duration = updates.pop("duration_minutes", 60)
    routes = [] if irrelevant == "missing" else [route_packet(duration=duration, **updates)]
    catalog = make_catalog(restaurant_packet(), visit_packet(), *routes)
    skeleton = parse_itinerary_composition(json.dumps(itinerary_draft([meal_placement(), visit_entry("09:10", "10:10")])))
    gaps = extract_local_connector_gaps(skeleton, catalog, weather_data_revision=0)
    assert unfilled_connector_gaps(catalog, gaps) == gaps
    _, composition = connect(skeleton, catalog)
    assert composition.days[0].placements[1].authored_route.duration_minutes == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("scheduled", [False, True])
@pytest.mark.parametrize("fast_access", ["eligible", "unadmitted", "hard_ineligible"])
async def test_feasible_provider_alternative_wins_despite_another_route_conflict(
    monkeypatch, scheduled, fast_access,
):
    from travel_agent.planning.itinerary import node
    from travel_agent.planning.research.ranking_contracts import CandidateRankingScore

    def timing(arrival):
        return {
            "departure_at": "2026-10-10T09:00:00+09:00",
            "arrival_at": f"2026-10-10T{arrival}:00+09:00",
        } if scheduled else {}

    catalog = make_catalog(
        restaurant_packet(), visit_packet(),
        route_packet(**timing("10:00")),
        route_packet("candidate_fast", 5, **timing("09:05")),
    )
    skeleton = parse_itinerary_composition(json.dumps(
        itinerary_draft([meal_placement(), visit_entry("09:10", "10:10")])
    ))
    spec = make_planning_state().intent_spec
    scores = []
    for score in rank_candidates(catalog=catalog, intent_spec=spec, matches=[]):
        payload = score.model_dump()
        if score.candidate_id in {"candidate_slow", "candidate_fast"}:
            assert score.hard_eligible
            payload["ranking_tuple"] = [2.0 if score.candidate_id == "candidate_slow" else 1.0]
        if score.candidate_id == "candidate_fast" and fast_access == "hard_ineligible":
            payload.update(hard_eligible=False, hard_violation_intent_ids=["intent_test"])
        scores.append(CandidateRankingScore.model_validate(payload))
    if fast_access == "unadmitted":
        catalog = catalog.model_copy(update={"admission_results": [
            result for result in catalog.admission_results
            if result.candidate_id != "candidate_fast"
        ]})
    catalog = catalog.model_copy(update={"candidate_ranking_scores": scores})
    selection = build_candidate_selection_plan(
        catalog=catalog, intent_spec=spec, ranking_scores=scores,
        duration_days=1, destination_count=1,
    )
    composition_ids = selection.composition_candidate_ids()
    assert "candidate_slow" in composition_ids
    assert ("candidate_fast" in composition_ids) == (fast_access == "eligible")
    current = restore_planning_state(
        make_planning_state(), recommendation_catalog=catalog, candidate_selection_plan=selection,
        placement_skeleton=skeleton, candidate_gate_status="passed",
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
    assert completed.placement_skeleton == skeleton
    assert completed.composition_repair_attempts == current.composition_repair_attempts
    if fast_access != "eligible":
        assert completed.trip_workspace_v2 is None
        assert completed.agent_status["itinerary_planner"] == "failed"
        assert "candidate_slow" in completed.composition_failure_context
        assert "duration=60min" in completed.composition_failure_context
        return

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
async def test_provider_time_conflict_returns_to_existing_bounded_revision(monkeypatch):
    from travel_agent.planning.itinerary import node
    from travel_agent.planning.research import node as candidate_gate

    catalog = make_catalog(restaurant_packet(), visit_packet(), route_packet())
    skeleton = parse_itinerary_composition(json.dumps(itinerary_draft([meal_placement(), visit_entry("09:10", "10:10")])))
    spec = make_planning_state().intent_spec
    catalog = catalog.model_copy(update={"candidate_ranking_scores": rank_candidates(
        catalog=catalog, intent_spec=spec, matches=[],
    )})
    selection = build_candidate_selection_plan(
        catalog=catalog, intent_spec=spec,
        ranking_scores=rank_candidates(catalog=catalog, intent_spec=spec, matches=[]),
        duration_days=1, destination_count=1,
    )
    current = restore_planning_state(
        make_planning_state(), recommendation_catalog=catalog, candidate_selection_plan=selection,
        placement_skeleton=skeleton, candidate_gate_status="passed",
        execution_plan=[["itinerary_planner"]], agent_status={"itinerary_planner": "pending"},
    )
    async def no_authoring(*args, **kwargs):
        pytest.fail("known provider conflict must not be replaced by an estimate")

    monkeypatch.setattr(node, "_author_connector_routes", no_authoring)
    failed = restore_planning_state(current, **await node.itinerary_planner_node(current, {}))
    assert failed.trip_workspace_v2 is None
    assert failed.placement_skeleton == skeleton
    assert "duration=60min" in failed.composition_failure_context
    assert failed.agent_status["itinerary_planner"] == "failed"
    repairing = restore_planning_state(failed, **await candidate_gate.candidate_gate_node(failed))
    assert repairing.composition_repair_attempts == 1
    assert candidate_gate.route_after_candidate_gate(repairing) == "composition_repair"
    fixed = itinerary_draft([meal_placement(), visit_entry("10:00", "11:00")])

    class Model:
        async def ainvoke(self, messages, **kwargs):
            assert "duration=60min" in messages[-1]["content"]
            return json.dumps(fixed)

    monkeypatch.setattr(node, "get_model_router", lambda: None)
    monkeypatch.setattr(node, "llm_for_task", lambda *args: Model())
    revised = restore_planning_state(repairing, **await node.itinerary_planner_node(repairing, {}))
    assert revised.placement_skeleton.days[0].placements[1].planned_start.hour == 10
    ready = restore_planning_state(revised, candidate_gate_status="passed")
    completed = restore_planning_state(ready, **await node.itinerary_planner_node(ready, {}))
    assert completed.agent_status["itinerary_planner"] == "completed"
    itinerary = completed.trip_workspace_v2.itinerary
    assert itinerary.transport_legs[0].duration_minutes == 60
    assert [stop.lineage.candidate_id for stop in itinerary.dining_stops] == ["candidate_dining"]
    assert [stop.lineage.candidate_id for stop in itinerary.visit_stops] == ["candidate_visit"]
    assert completed.placement_skeleton.days[0].placements[0] == skeleton.days[0].placements[0]


@pytest.mark.asyncio
async def test_connector_estimator_receives_real_names_and_cannot_shrink_time_window():

    catalog = make_catalog(restaurant_packet(), visit_packet())
    skeleton = parse_itinerary_composition(json.dumps(itinerary_draft([meal_placement(), visit_entry("09:10", "10:10")])))
    gaps = extract_local_connector_gaps(skeleton, catalog, weather_data_revision=0)

    class Model:
        async def ainvoke(self, messages, **kwargs):
            described = json.loads(messages[-1]["content"].split("：", 1)[1])[0]
            assert described["from_endpoint"]["name"] == "Cafe"
            assert described["to_endpoint"]["name"] == "candidate_visit"
            return json.dumps({"connectors": [{"gap_id": gaps[0].gap_id, "mode": "bus", "duration_minutes": 60, "selection_reason": "honest estimate"}]})

    authored = await connector_estimates._author_connector_routes(Model(), gaps)
    with pytest.raises(ItineraryCompositionError, match="cannot fit"):
        materialize_skeleton_connectors(skeleton, catalog, gaps, authored)


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
        assert any(admission.candidate_id == selected.candidate_id and admission.selection_slot_id == slot.selection_slot_id for admission in result.recommendation_catalog.admission_results)


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


def grounded_place_packet(packet, query_plan, *, country_code="JP"):
    from travel_agent.planning.requirements.intent_contracts import canonical_json_hash
    from travel_agent.planning.research.evidence import (
        FactAssertion,
        FactSourceLink,
        FieldProvenance,
    )
    from travel_agent.tools.governance import compiled_tool_source_id

    payload = packet.model_dump()
    candidate = payload["candidates"][0]
    candidate["provider_country_code"] = country_code
    if country_code == "CN":
        candidate.update(destination_id="destination_hangzhou", address="Hangzhou")
    domain = candidate["candidate_kind"]
    query = next(
        query for query in query_plan.queries
        if query.domain.value == domain
        and query.destination_id == candidate["destination_id"]
        and query.query_kind.value == "structural"
    )
    source = payload["source_records"][0]
    source_id = compiled_tool_source_id(source["tool_audit_id"], candidate["place_id"])
    identity = {
        field: candidate[field] for field in (
            "branch_name" if domain == "dining" else "name",
            "place_id", "address", "provider_place_type", "provider_country_code",
        )
    }
    identity.update(
        latitude=30.25 if country_code == "CN" else 35.68,
        longitude=120.16 if country_code == "CN" else 139.76,
    )
    source.update(
        source_record_id=source_id, snapshot=identity,
        content_hash=canonical_json_hash(identity),
    )
    entity = payload["fact_assertions"][0]["entity_ref"]
    facts = [
        FactAssertion(
            fact_assertion_id=f"fact_{candidate['candidate_id']}_{field}",
            entity_ref=entity, field_path=field, asserted_value=value,
            criticality="decision_critical", status="verified",
            source_links=[FactSourceLink(
                source_record_id=source_id, relation="supports",
                source_locator=field,
            )],
        )
        for field, value in identity.items()
    ]
    candidate.update(
        source_record_ids=[source_id],
        fact_assertion_ids=[fact.fact_assertion_id for fact in facts],
        field_paths=list(identity),
    )
    payload.update(
        research_query_plan_id=query_plan.query_plan_id,
        executed_query_ids=[query.query_id], fact_assertions=facts,
        field_provenance=[FieldProvenance(
            origin="external_fact", entity_ref=entity, field_path=fact.field_path,
            reference_ids=[fact.fact_assertion_id],
        ) for fact in facts],
    )
    payload["candidate_discovery_records"][0].update(
        query_ids=[query.query_id], intent_ids=[], origins=["structural_query"],
    )
    return ResearchPacket.model_validate(payload)


def research_ready_state(*, kinds=("visit",), second_destination=False, cn_food=False):
    from tests.fixtures.research_catalog import make_identity, make_research_brief
    from travel_agent.planning.requirements.identity_contracts import (
        ControlledTripIdentity,
    )
    from travel_agent.planning.research.brief_contracts import DomainResearchObjective
    from travel_agent.planning.research.query_planner import build_research_query_plan

    original = make_planning_state()
    identity = make_identity().model_dump(mode="json")
    identity.update(start_date="2026-10-10", end_date="2026-10-12")
    identity["origin"] = dict(identity["destinations"][0])
    if second_destination:
        identity["origin"] = make_identity().model_dump(mode="json")["origin"]
        identity["destinations"].append({
            **identity["destinations"][0], "place_id": "destination_osaka",
            "name": "Osaka", "display_name": "Osaka, Japan", "admin_path": ["Osaka"],
            "latitude": 34.69, "longitude": 135.5,
        })
    if cn_food:
        identity["destinations"][0].update(
            place_id="destination_hangzhou", name="Hangzhou", display_name="Hangzhou, China",
            country_code="CN", latitude=30.25, longitude=120.16, admin_path=["Hangzhou"],
        )
        identity["origin"] = dict(identity["destinations"][0])
        identity["style"].update(primary="food", secondary_interests=[])
    brief = make_research_brief(original.intent_spec).model_copy(update={
        "controlled_trip_identity": ControlledTripIdentity.model_validate(identity),
        "domain_objectives": [DomainResearchObjective(
            objective_id=f"objective_{kind}", domain=kind, summary=f"research {kind}",
        ) for kind in ("visit", "dining")],
    })
    plan = build_research_query_plan(intent_spec=original.intent_spec, brief=brief)
    packets = [grounded_place_packet(
        visit_packet() if kind == "visit" else restaurant_packet(), plan,
        country_code="CN" if cn_food else "JP",
    ) for kind in kinds]
    packet = packets[0].model_dump()
    for other in packets[1:]:
        for field in ("candidates", "candidate_discovery_records", "source_records", "fact_assertions", "field_provenance"):
            packet[field].extend(other.model_dump()[field])
        packet["executed_query_ids"].extend(other.executed_query_ids)
    for candidate in packet["candidates"]:
        candidate["research_packet_id"] = packet["research_packet_id"]
    packet = ResearchPacket.model_validate(packet)
    shell = original.minimum_delivery_draft.day_shells[0]
    draft = original.minimum_delivery_draft.model_copy(update={
        "constraint_pack_revision": 1,
        "day_shells": [shell.model_copy(update={
            "day_id": f"day_{day}", "day": day, "date": date(2026, 10, 9 + day),
            "destination_id": identity["destinations"][-1 if second_destination and day == 3 else 0]["place_id"],
            "arrival_from_destination_id": identity["destinations"][0]["place_id"] if second_destination and day == 3 else None,
            "lodging_night": day < 3,
        }) for day in range(1, 4)],
    })
    return restore_planning_state(
        original, controlled_trip_identity=identity, constraint_pack_revision=1,
        fact_data_revision=1, research_brief=brief, research_query_plan=plan,
        planning_generation=original.planning_generation.model_copy(update={"constraint_pack_revision": 1}),
        minimum_delivery_draft=draft, recommendation_catalog=None, candidate_selection_plan=None,
        research_packets={"destination_researcher": packet},
        execution_plan=[["destination_researcher"], ["itinerary_planner"]],
        agent_status={"destination_researcher": "completed", "itinerary_planner": "pending"},
    )


def offline_candidate_model(monkeypatch):
    class Model:
        async def ainvoke(self, messages, **kwargs):
            return json.dumps({"matches": []})

    monkeypatch.setattr(candidate_evaluation, "get_model_router", lambda: None)
    monkeypatch.setattr(candidate_evaluation, "llm_for_task", lambda *args: Model())


@pytest.mark.asyncio
@pytest.mark.parametrize("kinds", [("visit",), ("visit", "dining")])
async def test_real_candidate_gate_releases_reusable_places_to_planner(monkeypatch, kinds):
    from travel_agent.planning.research.node import (
        candidate_gate_node,
        route_after_candidate_gate,
    )

    offline_candidate_model(monkeypatch)
    current = research_ready_state(kinds=kinds)
    ready = restore_planning_state(current, **await candidate_gate_node(current))
    assert all(row.status == "passed" for row in ready.recommendation_catalog.admission_results)
    assert len(ready.recommendation_catalog.candidate_ranking_scores) == len(kinds)
    assert ready.candidate_selection_plan.composition_candidate_ids()
    assert len(ready.minimum_delivery_draft.day_shells) > len(kinds)
    assert route_after_candidate_gate(ready) == "itinerary_planner"
    assert not ready.candidate_research_gaps
    assert not ready.candidate_gate_attempts
    assert "destination_researcher" not in ready.agent_assignments


@pytest.mark.asyncio
async def test_real_candidate_gate_researches_the_destination_without_a_stop(monkeypatch):
    from travel_agent.planning.research.gaps import _gap_id
    from travel_agent.planning.research.node import candidate_gate_node

    offline_candidate_model(monkeypatch)
    current = research_ready_state(second_destination=True)
    pending = restore_planning_state(current, **await candidate_gate_node(current))
    assert pending.candidate_gate_route == "destination_researcher"
    gap, = pending.candidate_research_gaps
    assert (gap.gap_id, gap.field_path, gap.destination_id, gap.status) == (
        _gap_id("destination_researcher", "missing_destination_physical_stop", "destination_osaka"),
        "itinerary.destination_physical_stop", "destination_osaka", "researching",
    )
    scopes = pending.agent_assignments["destination_researcher"]["provider_evidence_assignments"]
    assert scopes
    assert all("destination_osaka" in row["scope"]["target_identity"] for row in scopes)
    objective = pending.agent_assignments["destination_researcher"]["objective"]
    assert gap.gap_id in objective and gap.destination_id in objective
    assert sum(pending.candidate_gate_attempts.values()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("available,missing,cn_food", [("dining", "visit", False), ("visit", "dining", True)])
async def test_real_candidate_gate_still_requires_noncompensating_physical_kinds(
    monkeypatch, available, missing, cn_food,
):
    from travel_agent.planning.research.node import candidate_gate_node

    offline_candidate_model(monkeypatch)
    current = research_ready_state(kinds=(available,), cn_food=cn_food)
    pending = restore_planning_state(current, **await candidate_gate_node(current))
    assert pending.recommendation_catalog.admission_results[0].status == "passed"
    assert pending.candidate_gate_route == "destination_researcher"
    gap, = pending.candidate_research_gaps
    assert gap.field_path == f"candidate_kind.{missing}"
    assert pending.agent_assignments["destination_researcher"]["required_candidate_kinds"] == [missing]


@pytest.mark.asyncio
async def test_real_candidate_gate_keeps_exact_long_distance_responsibilities(monkeypatch):
    from travel_agent.planning.requirements.route_legs import (
        build_required_long_distance_legs,
    )
    from travel_agent.planning.research.node import candidate_gate_node

    offline_candidate_model(monkeypatch)
    current = research_ready_state()
    identity = dict(current.controlled_trip_identity)
    identity["origin"] = {
        **identity["origin"], "place_id": "origin_shanghai", "name": "Shanghai",
        "display_name": "Shanghai, China", "country_code": "CN", "admin_path": ["Shanghai"],
        "latitude": 31.23, "longitude": 121.47,
    }
    current = restore_planning_state(current, controlled_trip_identity=identity,
        execution_plan=[["destination_researcher", "transport_researcher"], ["itinerary_planner"]])
    pending = restore_planning_state(current, **await candidate_gate_node(current))
    assert pending.candidate_gate_route == "transport_researcher"
    gaps = [gap for gap in pending.candidate_research_gaps if gap.field_path == "transport_class.long_distance"]
    assert len(gaps) == 2 and all(gap.status == "researching" for gap in gaps)
    assigned = pending.agent_assignments["transport_researcher"]["provider_evidence_assignments"]
    assert {row["scope"]["scope_id"] for row in assigned} == {gap.provider_evidence_scope_id for gap in gaps}
    assert {json.dumps(row["scope"]["route_leg"], sort_keys=True) for row in assigned} == {
        json.dumps(leg.model_dump(mode="json"), sort_keys=True)
        for leg in build_required_long_distance_legs(identity, cross_day_return_required=False)
    }
    assert sum(pending.candidate_gate_attempts.values()) == 1
