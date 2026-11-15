"""首轮铁路查询结果不依赖模型复述进入组合目录。"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from tests.fixtures.itinerary import itinerary_draft
from tests.fixtures.research_packets import make_packet
from travel_agent.planning.delivery.fact_projection import build_fact_snapshot
from travel_agent.planning.itinerary.materialize import materialize_trip_workspace
from travel_agent.planning.itinerary.parsing import parse_itinerary_composition
from travel_agent.planning.itinerary.prompts import _composition_catalog_json
from travel_agent.planning.requirements.generation_contracts import PlanningGeneration
from travel_agent.planning.requirements.inputs import UserInputAnchor
from travel_agent.planning.requirements.place_names import CONTROLLED_DESTINATION_ANCHOR_PREFIX
from travel_agent.planning.research.assembly import build_candidate_catalog
from travel_agent.planning.research.provider_assignments import (
    build_provider_evidence_assignments,
    dump_provider_evidence_assignments,
)
from travel_agent.planning.research.provider_contracts import ProviderRouteLegScope
from travel_agent.planning.research.transport import node
from travel_agent.planning.research.transport.rail import binding
from travel_agent.planning.state import TravelAgentState
from travel_agent.tools.result import ReactOutcome, ReactResult


DATE = date(2026, 11, 12)
IDENTITY = {
    "origin": {"place_id": "city_shanghai", "name": "上海", "country_code": "CN"},
    "destinations": [{"place_id": "city_hangzhou", "name": "杭州", "country_code": "CN"}],
    "start_date": DATE.isoformat(),
    "end_date": DATE.isoformat(),
}


def _assignment(*, return_leg=False):
    legs = [ProviderRouteLegScope(
        leg_role="outbound", from_place_id="city_shanghai", to_place_id="city_hangzhou",
        service_date=DATE,
    )]
    if return_leg:
        legs.append(ProviderRouteLegScope(
            leg_role="return", from_place_id="city_hangzhou", to_place_id="city_shanghai",
            service_date=DATE,
        ))
    return build_provider_evidence_assignments(
        run_id="run_test", worker_kind="transport_researcher",
        controlled_trip_identity=IDENTITY, prior_scope_attempts={},
        transport_classes=["long_distance"], long_distance_legs=legs,
    )


def _state(assignments):
    return TravelAgentState(
        run_id="run_test", controlled_trip_identity=deepcopy(IDENTITY),
        planning_generation=PlanningGeneration(generation_id="generation_test", revision=1),
        fact_data_revision=1,
        agent_assignments={"transport_researcher": {
            "objective": "查询真实交通", "provider_evidence_assignments":
                dump_provider_evidence_assignments(assignments),
        }},
    )


def _train(code="G123", origin="AOH", destination="HGH", departure="08:00", arrival="09:00"):
    return {
        "train_code": code, "from_name": "上海虹桥" if origin == "AOH" else "杭州东",
        "from_code": origin, "to_name": "杭州东" if destination == "HGH" else "上海虹桥",
        "to_code": destination, "departure_time": departure, "arrival_time": arrival,
        "duration_minutes": 60, "min_price_cny": 73.0,
    }


def _ticket(train, *, audit="audit-ticket", result_date=DATE.isoformat()):
    return {
        "tool_name": "get-tickets", "server_name": "12306-train", "status": "success",
        "audit_id": audit, "retrieved_at": "2026-11-10T10:00:00+00:00",
        "metadata": {"evidence_allowed": True},
        "sanitized_result": {
            "success": True, "provider": "12306", "date": result_date,
            "from_station": train["from_code"], "to_station": train["to_code"],
            "results": [train],
        },
    }


async def _execute_node(monkeypatch, *, assignments, raw, ticket_by_from, now=None):
    state = _state(assignments)

    class Registry:
        def has_tool(self, name):
            return name == "get-tickets"

    async def execute(name, arguments, **kwargs):
        assert name == "get-tickets"
        if arguments["fromStation"] == "TEMPORAL_PREFLIGHT":
            return {
                "tool_name": "get-tickets", "server_name": "12306-train",
                "status": "reference_only", "audit_id": "audit-preflight",
                "metadata": {"evidence_allowed": False}, "sanitized_result": {},
            }
        return deepcopy(ticket_by_from[arguments["fromStation"]])

    async def locate(*, telecode, **kwargs):
        return {"AOH": (31.194, 121.320), "HGH": (30.292, 120.213)}[telecode]

    async def available():
        return []

    async def react(**kwargs):
        return ReactResult(outcome=ReactOutcome.FINAL_ANSWER, content=json.dumps(raw, ensure_ascii=False))

    discover = binding.discover_domestic_rail_route

    async def discover_at_fixed_time(**kwargs):
        return await discover(**kwargs, now=now or datetime(2026, 11, 10, tzinfo=timezone.utc))

    monkeypatch.setattr(binding, "get_tool_registry", lambda: Registry())
    monkeypatch.setattr(binding, "execute_tool", execute)
    monkeypatch.setattr(binding, "_locate_rail_station", locate)
    monkeypatch.setattr(node, "discover_domestic_rail_route", discover_at_fixed_time)
    monkeypatch.setattr(node, "get_model_router", lambda: object())
    monkeypatch.setattr(node, "llm_for_task", lambda *args, **kwargs: SimpleNamespace())
    monkeypatch.setattr(node, "get_available_tools", available)
    monkeypatch.setattr(node, "streaming_react_loop", react)
    result = await node.transport_researcher_node(state, {"configurable": {}})
    assert result["agent_status"]["transport_researcher"] == "completed", result
    packet = next(iter(result["research_packets"].values()))
    updated = state.model_copy(update={"research_packets": result["research_packets"]})
    catalog, _ = build_candidate_catalog(updated)
    return packet, catalog, updated, result


async def test_empty_react_packet_retains_local_train(monkeypatch):
    train = _train()
    route = binding._build_rail_route_envelope(
        train=train, start_date=DATE.isoformat(), audit_id="audit-ticket",
        retrieved_at="2026-11-10T10:00:00+00:00", from_point=None, to_point=None,
    )["sanitized_result"]["routes"][0]
    route["transport_class"] = "public_transit"
    route["selected_mode"] = "metro"
    route["segments"][0]["mode"] = "metro"
    local = make_packet(worker="transport_researcher").model_dump(mode="json")["candidates"][0]
    local.update(route, candidate_id="model_local", destination_id="city_hangzhou", booking_status="not_required")
    packet, _, _, _ = await _execute_node(
        monkeypatch, assignments=_assignment(),
        raw={"candidates": [local], "source_records": [], "fact_assertions": [], "field_provenance": []},
        ticket_by_from={"AOH": _ticket(train)},
    )
    assert {item.candidate_id for item in packet.candidates} >= {"model_local"}
    assert len(packet.candidates) == 2


async def test_initial_selected_train_reaches_composition_and_delivery(monkeypatch):
    train = _train()
    packet, catalog, state, result = await _execute_node(
        monkeypatch, assignments=_assignment(), raw={"candidates": []},
        ticket_by_from={"AOH": _ticket(train)},
    )
    assert len(packet.candidates) == 1
    candidate = packet.candidates[0]
    assert candidate.provider_evidence_scope_id == _assignment()[0].scope.scope_id
    assert candidate.segments[0].service_number == "G123"
    assert candidate.from_endpoint.station_code == "AOH"
    assert candidate.to_endpoint.station_code == "HGH"
    assert candidate.from_endpoint.latitude == 31.194
    assert candidate.departure_at.date() == DATE
    assert candidate.arrival_at.hour == 9
    assert result["provider_evidence_outcomes"][candidate.provider_evidence_scope_id].status == "materialized"
    assert candidate.candidate_id in catalog.candidate_index()
    text = _composition_catalog_json(state.model_copy(update={"recommendation_catalog": catalog}), skeleton_only=True)
    assert "G123" in text and "上海虹桥" in text and "杭州东" in text and DATE.isoformat() in text

    draft = itinerary_draft([{"placement_kind": "transport", "candidate_id": candidate.candidate_id}])
    draft["days"][0].update(date=DATE.isoformat(), destination_id="city_hangzhou")
    workspace = materialize_trip_workspace(
        run_id="run_test", workspace_revision=0,
        composition=parse_itinerary_composition(json.dumps(draft)),
        catalog=catalog, requirements="", composition_mutations=[],
        user_input_anchors=[UserInputAnchor(
            anchor_id="destination", field_path=f"{CONTROLLED_DESTINATION_ANCHOR_PREFIX}city_hangzhou",
            value={"place_id": "city_hangzhou", "name": "杭州"}, input_kind="controlled_identity",
        )],
    )
    leg = workspace.itinerary.transport_legs[0]
    assert leg.segments[0].service_number == "G123"
    assert leg.from_endpoint.station_code == "AOH"
    assert leg.departure_at.date() == DATE
    assert leg.lineage.source_record_ids
    facts = build_fact_snapshot(workspace)
    source = next(source for source in facts.source_records if source.tool_audit_id == "audit-ticket")
    assert source.snapshot["sanitized_result"]["results"][0]["train_code"] == "G123"
    assert any(fact.field_path == "segments" for fact in facts.fact_assertions)


async def test_same_day_return_gets_its_own_real_scope_and_date(monkeypatch):
    outbound = _train()
    inbound = _train("G124", "HGH", "AOH", "19:00", "20:00")
    assignments = _assignment(return_leg=True)
    packet, catalog, _, _ = await _execute_node(
        monkeypatch, assignments=assignments, raw={"candidates": []},
        ticket_by_from={"AOH": _ticket(outbound), "HGH": _ticket(inbound, audit="audit-return")},
    )
    assert len(catalog.candidate_index()) == 2
    by_number = {item.segments[0].service_number: item for item in packet.candidates}
    assert by_number["G123"].provider_evidence_scope_id == assignments[0].scope.scope_id
    assert by_number["G124"].provider_evidence_scope_id == assignments[1].scope.scope_id
    assert by_number["G124"].destination_id == "city_hangzhou"
    assert by_number["G124"].departure_at.date() == DATE


async def test_model_candidate_for_same_service_is_not_duplicated(monkeypatch):
    train = _train()
    route = binding._build_rail_route_envelope(
        train=train, start_date=DATE.isoformat(), audit_id="audit-ticket",
        retrieved_at="2026-11-10T10:00:00+00:00", from_point=None, to_point=None,
    )["sanitized_result"]["routes"][0]
    raw = make_packet(worker="transport_researcher").model_dump(mode="json")
    raw.update(source_records=[], fact_assertions=[], field_provenance=[])
    candidate = raw["candidates"][0]
    candidate.update(route, destination_id="city_hangzhou", booking_status="unknown")
    candidate["segments"][0]["service_number"] = None
    packet, catalog, _, _ = await _execute_node(
        monkeypatch, assignments=_assignment(), raw=raw,
        ticket_by_from={"AOH": _ticket(train)},
    )
    assert len(packet.candidates) == len(catalog.candidate_index()) == 1
    candidate = packet.candidates[0]
    assert candidate.candidate_id == "visit_a"
    assert candidate.segments[0].service_number == "G123"
    assert candidate.from_endpoint.latitude == 31.194
    assert candidate.source_record_ids
    assert candidate.selection_reasons == ["identity verified", "fits visit"]
    assert candidate.tradeoff == "fixture"


def test_merge_preserves_non_rail_facts_sources_and_existing_references():
    packet = make_packet(worker="transport_researcher")
    original = packet.candidates[0]
    train = _train()
    route = binding._build_rail_route_envelope(
        train=train, start_date=DATE.isoformat(), audit_id="audit-ticket",
        retrieved_at="2026-11-10T10:00:00+00:00", from_point=None, to_point=None,
    )["sanitized_result"]["routes"][0]
    payload = packet.model_dump(mode="python")
    payload["candidates"][0].update(route)
    payload["candidates"][0]["booking_status"] = "recommended"
    payload["candidates"][0]["active_constraint_ids"] = ["constraint_1"]
    payload["candidates"][0]["constraint_evaluations"] = [{
        "constraint_id": "constraint_1", "status": "passed",
        "fact_assertion_ids": ["fact_visit_a_accessibility_metadata"],
    }]
    packet = type(packet).model_validate(payload)
    state = _state(_assignment())
    envelope = _ticket(train)
    envelope["metadata"].update(
        rail_selected_train={key: train[key] for key in ("train_code", "from_code", "to_code")},
        rail_route_leg=_assignment()[0].scope.route_leg.model_dump(mode="json"),
        rail_scope_id=_assignment()[0].scope.scope_id,
    )
    from travel_agent.planning.research.catalog import RecommendationCatalog
    from travel_agent.planning.research.transport.rail.followup import compile_rail_followup_packet

    rail = compile_rail_followup_packet(
        state=state,
        catalog=RecommendationCatalog(
            generation_id=packet.generation_id, fact_data_revision=packet.fact_data_revision,
            weather_data_revision=0, research_packets=[packet],
        ),
        envelope=envelope, task_id="transport_researcher", existing_candidate_ids=set(),
        service_date=DATE.isoformat(),
    )
    assert rail is not None
    merged = node._merge_initial_rail_packet(packet, rail, active_constraint_ids=[])
    candidate = merged.candidates[0]
    assert len(merged.candidates) == 1
    assert candidate.candidate_id == original.candidate_id
    assert candidate.booking_status == "recommended"
    assert candidate.constraint_evaluations[0].fact_assertion_ids == [
        "fact_visit_a_accessibility_metadata"
    ]
    assert candidate.selection_reasons == original.selection_reasons
    assert "source_visit_a" in candidate.source_record_ids
    assert any(source.tool_audit_id == "audit-ticket" for source in merged.source_records)
    assert any(fact.field_path == "accessibility_metadata" for fact in merged.fact_assertions)
    assert any(fact.field_path == "segments" and fact.asserted_value[0]["service_number"] == "G123" for fact in merged.fact_assertions)
    assert not any(fact.field_path == "route_id" and fact.asserted_value != candidate.route_id for fact in merged.fact_assertions)


async def test_cross_day_scope_is_not_assigned_to_a_same_day_train(monkeypatch):
    leg = ProviderRouteLegScope(
        leg_role="outbound", from_place_id="city_shanghai", to_place_id="city_hangzhou",
        service_date=DATE, cross_day_required=True,
    )
    assignments = build_provider_evidence_assignments(
        run_id="run_test", worker_kind="transport_researcher",
        controlled_trip_identity=IDENTITY, prior_scope_attempts={},
        transport_classes=["long_distance"], long_distance_legs=[leg],
    )
    packet, _, _, _ = await _execute_node(
        monkeypatch, assignments=assignments, raw={"candidates": []},
        ticket_by_from={"AOH": _ticket(_train())},
    )
    assert packet.candidates[0].provider_evidence_scope_id is None
    assert packet.candidates[0].segments[0].service_number == "G123"


async def test_train_selection_and_provenance_use_original_matching_row(monkeypatch):
    later = _train("G199", departure="10:00", arrival="11:00")
    earlier = _train()
    foreign = _train("G888", "VNP", "HGH")
    ticket = _ticket(later)
    ticket["sanitized_result"]["results"] = [later, foreign, earlier]
    packet, _, _, _ = await _execute_node(
        monkeypatch, assignments=_assignment(), raw={"candidates": []},
        ticket_by_from={"AOH": ticket},
    )
    assert [item.segments[0].service_number for item in packet.candidates] == ["G123"]
    source = next(source for source in packet.source_records if source.tool_audit_id == "audit-ticket")
    assert [row["train_code"] for row in source.snapshot["sanitized_result"]["results"]] == [
        "G199", "G888", "G123",
    ]
    service = next(fact for fact in packet.fact_assertions if fact.field_path == "segments")
    assert service.source_links[0].source_locator == "sanitized_result.results[2]"


async def test_unrelated_model_candidate_is_preserved(monkeypatch):
    raw = make_packet(worker="transport_researcher").model_dump(mode="json")
    raw.update(source_records=[], fact_assertions=[], field_provenance=[])
    packet, catalog, _, _ = await _execute_node(
        monkeypatch, assignments=_assignment(), raw=raw,
        ticket_by_from={"AOH": _ticket(_train())},
    )
    assert len(packet.candidates) == len(catalog.candidate_index()) == 2
    assert catalog.candidate_index()["visit_a"].selected_mode.value == "metro"
    assert any(item.segments[0].service_number == "G123" for item in packet.candidates)


@pytest.mark.parametrize("result_date", ["2026-11-11", "2026-11-13"])
async def test_mismatched_result_date_is_not_misrepresented(monkeypatch, result_date):
    packet, catalog, _, _ = await _execute_node(
        monkeypatch, assignments=_assignment(), raw={"candidates": []},
        ticket_by_from={"AOH": _ticket(_train(), result_date=result_date)},
    )
    assert not packet.candidates
    assert not catalog.candidate_index()


async def test_reference_day_is_not_compiled_as_requested_train(monkeypatch):
    packet, catalog, _, result = await _execute_node(
        monkeypatch, assignments=_assignment(), raw={"candidates": []},
        ticket_by_from={"AOH": _ticket(_train(), result_date="2026-10-15")},
        now=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    assert not packet.candidates
    assert not catalog.candidate_index()
    reference = result["provider_reference_services"][0]
    assert reference.reference_date == date(2026, 10, 15)
    assert reference.requested_date == DATE
