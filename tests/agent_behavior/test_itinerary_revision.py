import json
from datetime import date, datetime, timedelta

import pytest

from travel_agent.agents.itinerary_planner.node import (
    _build_composition_prompt,
    _composition_phase,
    parse_itinerary_composition,
)
from travel_agent.entities.itinerary_composition_v2 import (
    ItineraryCompositionDraft,
    materialize_trip_workspace,
)
from travel_agent.entities.intent_coverage import IntentContractSnapshot
from travel_agent.entities.state import TravelAgentState
from tests.test_composition_context import state
from tests.agent_behavior.test_intent_research_ranking_selection import (
    _catalog,
    _packet,
    _local_transport_packet,
)
from travel_agent.entities.candidate_discovery import CandidateDiscoveryOrigin
from travel_agent.entities.delivery_bundle import DiningCandidate, ResearchPacket
from travel_agent.entities.itinerary_composition_v2 import (
    AuthoredRoute,
    ItineraryCompositionError,
    extract_local_connector_gaps,
    materialize_skeleton_connectors,
    placement_occurrence_key,
    validate_itinerary_transport_topology,
    validate_placement_skeleton,
)
from travel_agent.services.candidate_selection import build_candidate_selection_plan
from travel_agent.services.candidate_ranking import rank_candidates


def checkpoint(current, **update):
    payload = current.model_dump()
    payload.update(update)
    return TravelAgentState.model_validate(payload)


def visit_packet(candidate_id="candidate_visit"):
    return _packet(
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
    spec = intent_spec or state().intent_spec
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


def visit(start="10:00", end="11:00"):
    return {
        **meal(start=start, end=end),
        "placement_kind": "visit",
        "candidate_id": "candidate_visit",
        "meal_type": None,
    }


def visit_entry(start="10:00", end="11:00"):
    result = visit(start, end)
    result.pop("meal_type")
    return result


def long_distance_packet(candidate_id, origin, destination, start, end, scope):
    packet = _local_transport_packet(
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


def meal(meal_type="breakfast", start="08:00", end="09:00", day="2026-10-10"):
    return {
        "placement_kind": "dining",
        "candidate_id": "candidate_dining",
        "meal_type": meal_type,
        "duration_minutes": 60,
        "planned_start": f"{day}T{start}:00+09:00",
        "planned_end": f"{day}T{end}:00+09:00",
    }


def draft(placements=None):
    return {
        "itinerary_id": "itinerary_test",
        "title": "Tokyo",
        "duration_days": 1,
        "days": [
            {
                "day_id": "day_1",
                "day": 1,
                "date": "2026-10-10",
                "destination_id": "destination_tokyo",
                "placements": placements or [meal()],
            }
        ],
    }


def test_repeated_restaurant_is_an_occurrence_not_a_global_identity():
    payload = draft([meal(), meal("lunch", "12:00", "13:00")])
    payload["days"].append(
        {
            **payload["days"][0],
            "day_id": "day_2",
            "day": 2,
            "date": "2026-10-11",
            "placements": [meal(day="2026-10-11")],
        }
    )
    payload["duration_days"] = 2
    result = parse_itinerary_composition(json.dumps(payload))
    assert [len(day.placements) for day in result.days] == [2, 1]


def test_duplicate_same_meal_is_reported_not_removed():
    with pytest.raises(ValueError, match="duplicate|more than once"):
        parse_itinerary_composition(json.dumps(draft([meal(), meal()])))


def test_short_valid_transition_is_not_shifted():
    payload = draft([meal(), visit_entry("09:05", "10:05")])
    result = parse_itinerary_composition(json.dumps(payload))
    catalog = _catalog(restaurant_packet(), visit_packet())
    gaps, composition = connect(result, catalog)
    final = workspace(composition, catalog)
    assert gaps[0].latest_arrival_time - gaps[0].departure_time == timedelta(minutes=5)
    assert final.itinerary.visit_stops[0].planned_start == datetime.fromisoformat(
        "2026-10-10T09:05:00+09:00"
    )


def test_mixed_timezone_schedule_is_correctable_validation_error():
    placement = meal()
    placement["planned_end"] = "2026-10-10T09:00:00"
    with pytest.raises(ValueError, match="timezone|UTC offset"):
        ItineraryCompositionDraft.model_validate(draft([placement]))


def test_revision_prompt_contains_existing_daily_draft_and_current_problem():
    original = state().model_copy(
        update={
            "placement_skeleton": ItineraryCompositionDraft.model_validate(draft()),
            "composition_failure_context": "rest overlaps train",
        }
    )
    prompt = _build_composition_prompt(original, "repair rest", skeleton_only=True)
    assert "rest overlaps train" in prompt.runtime
    assert "candidate_dining" in prompt.runtime
    assert "2026-10-10T08:00:00+09:00" in prompt.runtime


def test_failed_materialization_returns_to_draft_revision():
    current = state().model_copy(
        update={
            "placement_skeleton": ItineraryCompositionDraft.model_validate(draft()),
            "composition_failure_context": "rest overlaps train",
        }
    )
    assert _composition_phase(current) == "placement_skeleton"


@pytest.mark.parametrize("provider", [False, True])
def test_occurrences_reach_connectors_workspace_and_checkpoint(provider):
    routes = (
        [
            _local_transport_packet(
                "candidate_to_museum",
                origin_place_id="place_candidate_dining",
                destination_place_id="place_candidate_visit",
            ),
            _local_transport_packet(
                "candidate_to_cafe",
                origin_place_id="place_candidate_visit",
                destination_place_id="place_candidate_dining",
            ),
        ]
        if provider
        else []
    )
    catalog = _catalog(restaurant_packet(), visit_packet(), *routes)
    payload = draft(
        [
            meal(),
            visit_entry(),
            meal("lunch", "12:00", "13:00"),
            visit_entry("14:00", "15:00"),
            meal("dinner", "18:00", "19:00"),
        ]
    )
    payload["days"].append(
        {
            **payload["days"][0],
            "day_id": "day_2",
            "day": 2,
            "date": "2026-10-11",
            "placements": [meal(day="2026-10-11")],
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
    restored = checkpoint(
        state(),
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
    from travel_agent.entities.provider_evidence import ProviderRouteLegScope

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
    catalog = _catalog(inbound, outbound, visit_packet())
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
                draft([transport("candidate_in"), *stops, transport("candidate_out")])
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
            json.dumps(draft([transport("candidate_in")]))
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
    from travel_agent.agents.itinerary_planner import node
    from travel_agent.agents.orchestrator import candidate_gate, dispatcher

    from travel_agent.entities.intent_spec import IntentKind, IntentTarget
    from tests.agent_behavior.test_intent_research_ranking_selection import _intent, _spec

    objective = _intent("intent_trip", "Tokyo day trip", kind=IntentKind.OBJECTIVE)
    spec = _spec(objective.model_copy(update={"target": IntentTarget.TRIP, "impact_stages": ["composition"]}))
    original = state()
    original = checkpoint(
        original, intent_spec=spec,
        planning_generation=original.planning_generation.model_copy(update={"intent_hash": spec.content_hash}),
        minimum_delivery_draft=original.minimum_delivery_draft.model_copy(update={"intent_spec_hash": spec.content_hash}),
    )
    catalog = _catalog(visit_packet())
    catalog = catalog.model_copy(
        update={
            "candidate_ranking_scores": rank_candidates(
                catalog=catalog,
                intent_spec=spec,
                matches=[],
            )
        }
    )
    skeleton = parse_itinerary_composition(json.dumps(draft([visit_entry()])))
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
    current = checkpoint(
        original,
        recommendation_catalog=catalog,
        candidate_selection_plan=plan,
        placement_skeleton=bad,
        candidate_gate_status="passed",
        execution_plan=[["itinerary_planner"]],
        agent_status={"itinerary_planner": "pending"},
    )
    failed = checkpoint(current, **await node.itinerary_planner_node(current, {}))
    assert "free time" in failed.composition_failure_context
    routed = checkpoint(failed, **await dispatcher.dispatcher_node(failed))
    assert dispatcher.route_after_dispatcher(routed) == "candidate_gate"
    repairing = checkpoint(routed, **await candidate_gate.candidate_gate_node(routed))
    assert candidate_gate.route_after_candidate_gate(repairing) == "composition_repair"
    assert repairing.composition_repair_attempts == 1
    from travel_agent.services.intent_verification import evaluate_intent_fidelity
    from travel_agent.services.composition_rule_compiler import compile_composition_rules

    prior_workspace = workspace(skeleton, catalog, intent_spec=spec)
    report, gaps = evaluate_intent_fidelity(
        intent_spec=repairing.intent_spec,
        rules=compile_composition_rules(repairing.intent_spec),
        workspace=prior_workspace,
        repair_budget_exhausted=False,
    )
    assert report.items and report.items[0].status.value == "satisfied"
    repairing = checkpoint(
        repairing,
        trip_workspace_v2=prior_workspace.model_copy(update={"intent_coverage_report": report}),
        intent_coverage_report=report,
        intent_fidelity_gaps=gaps,
        intent_fidelity_route="composition_repair",
        delivery_quality_route="composition_repair",
    )
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
    revised = checkpoint(repairing, **await node.itinerary_planner_node(repairing, {}))
    assert revised.trip_workspace_v2 is None and not revised.local_connector_gaps
    assert revised.intent_coverage_report is None
    assert revised.intent_fidelity_gaps == []
    assert revised.intent_fidelity_route is None
    assert revised.recommendation_quality is None
    assert revised.delivery_quality_gaps == []
    assert revised.delivery_quality_route is None
    assert revised.intent_spec == repairing.intent_spec
    assert revised.recommendation_catalog == repairing.recommendation_catalog
    routed = checkpoint(revised, **await dispatcher.dispatcher_node(revised))
    assert dispatcher.route_after_dispatcher(routed) == "candidate_gate"
    monkeypatch.setattr(
        candidate_gate,
        "build_candidate_catalog",
        lambda state: (state.recommendation_catalog, [], []),
    )

    async def evaluate(**kwargs):
        return [], {}

    monkeypatch.setattr(candidate_gate, "evaluate_candidate_intents", evaluate)
    monkeypatch.setattr(candidate_gate, "get_model_router", lambda: None)
    monkeypatch.setattr(candidate_gate, "llm_for_task", lambda *args: None)
    ready = checkpoint(routed, **await candidate_gate.candidate_gate_node(routed))
    assert candidate_gate.route_after_candidate_gate(ready) == "passed"
    routed = checkpoint(ready, **await dispatcher.dispatcher_node(ready))
    assert dispatcher.route_after_dispatcher(routed) == "itinerary_planner"
    completed = checkpoint(routed, **await node.itinerary_planner_node(routed, {}))
    assert completed.agent_status["itinerary_planner"] == "completed"
    assert completed.intent_coverage_report is None
    assert completed.trip_workspace_v2.intent_coverage_report is None
    block = completed.trip_workspace_v2.itinerary.custom_blocks[0]
    assert block.planned_start.isoformat() == "2026-10-10T11:00:00+09:00"
    assert block.planned_end.isoformat() == "2026-10-10T12:00:00+09:00"


@pytest.mark.asyncio
async def test_revision_model_receives_distinct_actual_drafts(monkeypatch):
    from travel_agent.agents.itinerary_planner import node

    catalog = _catalog(restaurant_packet())
    seen = []

    class Model:
        async def ainvoke(self, messages, **kwargs):
            seen.append(messages[-1]["content"])
            return json.dumps(draft())

    for label in ("旧稿甲", "旧稿乙"):
        payload = draft()
        payload["title"] = label
        current = checkpoint(
            state(),
            recommendation_catalog=catalog,
            placement_skeleton=ItineraryCompositionDraft.model_validate(payload),
            composition_failure_context="rest conflict",
        )
        await node._compose_draft(current, "revise", Model(), set(), [], set())
    assert seen[0] != seen[1]
    assert "旧稿甲" in seen[0] and "旧稿乙" in seen[1]


@pytest.mark.asyncio
async def test_new_draft_researches_connectors_then_uses_the_same_materializer(
    monkeypatch,
):
    from travel_agent.agents.itinerary_planner import node
    from travel_agent.agents.orchestrator import candidate_gate, dispatcher
    from travel_agent.services.research_query_planner import build_research_query_plan
    from tests.agent_behavior.test_intent_research_ranking_selection import _brief

    catalog = _catalog(visit_packet(), restaurant_packet())
    skeleton = ItineraryCompositionDraft.model_validate(
        draft([visit_entry(), meal("dinner", "18:00", "19:00")])
    )
    current = state()
    query_plan = build_research_query_plan(
        intent_spec=current.intent_spec, brief=_brief(current.intent_spec)
    )
    current = checkpoint(
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

    monkeypatch.setattr(candidate_gate, "evaluate_candidate_intents", evaluate)
    monkeypatch.setattr(candidate_gate, "get_model_router", lambda: None)
    monkeypatch.setattr(candidate_gate, "llm_for_task", lambda *args: None)
    pending = checkpoint(current, **await candidate_gate.candidate_gate_node(current))
    assert candidate_gate.route_after_candidate_gate(pending) == "transport_researcher"
    assert len(pending.local_connector_gaps) == 1
    gap = pending.local_connector_gaps[0]
    route_packet = _local_transport_packet(
        "candidate_connection",
        origin_place_id=gap.from_place_id,
        destination_place_id=gap.to_place_id,
    )
    with_route = _catalog(visit_packet(), restaurant_packet(), route_packet)
    pending = checkpoint(pending, recommendation_catalog=with_route)
    ready = checkpoint(pending, **await candidate_gate.candidate_gate_node(pending))
    assert candidate_gate.route_after_candidate_gate(ready) == "passed"
    routed = checkpoint(ready, **await dispatcher.dispatcher_node(ready))
    assert dispatcher.route_after_dispatcher(routed) == "itinerary_planner"
    completed = checkpoint(routed, **await node.itinerary_planner_node(routed, {}))
    assert completed.agent_status["itinerary_planner"] == "completed"
    assert (
        completed.trip_workspace_v2.itinerary.transport_legs[0].lineage.candidate_id
        == "candidate_connection"
    )


@pytest.mark.asyncio
async def test_located_retry_keeps_new_reasons_and_reuses_provider_identity(
    monkeypatch,
):
    from travel_agent.agents.itinerary_planner import node
    from travel_agent.entities.itinerary_composition_v2 import authored_places

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
    payload = draft([entry, meal("dinner", "18:00", "19:00")])
    payload["days"][0]["placements"][1]["planned_start"] = "2026-10-10T11:00:00+09:00"
    payload["days"][0]["placements"][1]["planned_end"] = "2026-10-10T12:01:00+09:00"
    current = checkpoint(state(), recommendation_catalog=_catalog(restaurant_packet()))
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

    monkeypatch.setattr(node, "resolve_authored_place", resolve)
    monkeypatch.setattr(node, "_authored_place_tool_access", lambda state: None)

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
    result = await node._compose_draft(current, "revise", model, set(), [], set())
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
    catalog = _catalog(packet)
    payload = draft([transport("candidate_night")])
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
    checkpoint(state(), trip_workspace_v2=result)


def test_lodging_morning_and_evening_are_distinct_occurrences():
    from travel_agent.entities.delivery_bundle import LodgingCandidate

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
    catalog = _catalog(restaurant_packet(), ResearchPacket.model_validate(payload))
    payload = draft([meal("lunch", "12:00", "13:00")])
    payload.update(duration_days=3, lodging_candidate_ids=["candidate_hotel"])
    for day in (2, 3):
        local_date = f"2026-10-{day + 9}"
        payload["days"].append(
            {
                **payload["days"][0],
                "day_id": f"day_{day}",
                "day": day,
                "date": local_date,
                "placements": [meal("lunch", "12:00", "13:00", local_date)],
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
    checkpoint(state(), placement_skeleton=skeleton, trip_workspace_v2=result)


@pytest.mark.asyncio
async def test_existing_revision_budget_stops_reopening_the_broken_draft():
    from travel_agent.agents.orchestrator import candidate_gate, dispatcher
    from travel_agent.workflows.composition_repair import (
        MAXIMUM_COMPOSITION_REPAIR_ATTEMPTS,
    )

    current = checkpoint(
        state(),
        composition_repair_attempts=MAXIMUM_COMPOSITION_REPAIR_ATTEMPTS,
        composition_failure_context="rest overlaps activity",
        placement_skeleton=ItineraryCompositionDraft.model_validate(draft()),
        candidate_gate_status="passed",
        execution_plan=[["itinerary_planner"]],
        agent_status={"itinerary_planner": "failed"},
    )
    routed = checkpoint(current, **await dispatcher.dispatcher_node(current))
    assert dispatcher.route_after_dispatcher(routed) == "to_check"
    exhausted = checkpoint(current, **await candidate_gate.candidate_gate_node(current))
    assert candidate_gate.route_after_candidate_gate(exhausted) == "passed"
    assert exhausted.composition_repair_attempts == MAXIMUM_COMPOSITION_REPAIR_ATTEMPTS
