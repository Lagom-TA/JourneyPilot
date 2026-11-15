"""航班号只能从选中路线的可信逐段证据恢复。"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import json

import pytest

from tests.fixtures.itinerary import itinerary_draft
from tests.fixtures.research_catalog import make_catalog
from tests.fixtures.research_packets import make_packet
from travel_agent.planning.delivery.assembly import assemble_delivery_bundle
from travel_agent.planning.delivery.bundle import DeliveryBundle
from travel_agent.planning.delivery.fact_projection import build_fact_snapshot
from travel_agent.planning.delivery.projection_builder import build_delivery_projections
from travel_agent.planning.delivery.public.bundle import public_delivery_bundle
from travel_agent.planning.itinerary.materialize import materialize_trip_workspace
from travel_agent.planning.itinerary.parsing import parse_itinerary_composition
from travel_agent.planning.requirements.inputs import UserInputAnchor
from travel_agent.planning.requirements.place_names import CONTROLLED_DESTINATION_ANCHOR_PREFIX
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.evidence import FactStoreSnapshot
from travel_agent.planning.research.output.finalization import parse_research_packet
from travel_agent.planning.research.output.identifiers import _provider_fact_id, _provider_route_source_id
from travel_agent.planning.research.output.parsing import parse_research_packet_output
from travel_agent.planning.research.output.transcript import (
    _successful_route_records,
    authoritative_tool_messages,
)
from travel_agent.planning.research.provider_contracts import (
    ProviderEvidenceScope,
    ProviderRouteLegScope,
)
from travel_agent.planning.research.provider_scope_ids import provider_evidence_scope_id
from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.weather.models import WeatherContextSnapshot
from travel_agent.tools.governance import build_tool_execution_envelope


def _endpoint(code):
    return {"name": code, "place_id": f"iata:{code}", "station_code": code}


def _route():
    pvg, nrt, hnd = (_endpoint(code) for code in ("PVG", "NRT", "HND"))
    segments = [
        {
            "segment_id": "seg_a", "mode": "flight",
            "from_endpoint": pvg, "to_endpoint": nrt,
            "departure_at": "2026-11-20T09:00:00+08:00",
            "arrival_at": "2026-11-20T13:00:00+09:00",
            "duration_minutes": 180,
            "operator_name": "全日空", "service_number": "NH920",
        },
        {
            "segment_id": "seg_b", "mode": "flight",
            "from_endpoint": nrt, "to_endpoint": hnd,
            "departure_at": "2026-11-20T15:00:00+09:00",
            "arrival_at": "2026-11-20T16:00:00+09:00",
            "duration_minutes": 60,
            "operator_name": "全日空", "service_number": "NH221",
        },
    ]
    return {
        "route_id": "duffel:offer_1", "provider": "duffel",
        "transport_class": "long_distance", "selected_mode": "flight",
        "from_endpoint": pvg, "to_endpoint": hnd,
        "departure_at": segments[0]["departure_at"],
        "arrival_at": segments[-1]["arrival_at"],
        "duration_minutes": 420, "segments": segments,
    }


def _scope(*, origin="iata:PVG", destination="iata:HND", day=date(2026, 11, 20), run_id="run_test", cross_day=False):
    leg = ProviderRouteLegScope(
        leg_role="outbound", from_place_id=origin, to_place_id=destination,
        service_date=day, cross_day_required=cross_day,
    )
    fields = {
        "run_id": run_id, "worker_kind": "transport_researcher",
        "research_domain": ResearchDomain.LONG_DISTANCE_TRANSPORT,
        "candidate_kind": None, "transport_class": "long_distance",
        "target_identity": None, "route_leg": leg,
    }
    return ProviderEvidenceScope(scope_id=provider_evidence_scope_id(**fields), **fields)


def _payload(route=None, scope=None):
    route = route or _route()
    scope = scope or _scope()
    payload = make_packet(worker="transport_researcher").model_dump(mode="json")
    payload.update(source_records=[], fact_assertions=[], field_provenance=[])
    candidate = payload["candidates"][0]
    for field in (
        "route_id", "transport_class", "selected_mode", "from_endpoint", "to_endpoint",
        "departure_at", "arrival_at", "duration_minutes", "segments",
    ):
        candidate[field] = deepcopy(route[field])
    candidate["provider_evidence_scope_id"] = scope.scope_id
    candidate["fact_assertion_ids"] = []
    candidate["field_paths"] = []
    candidate["source_record_ids"] = []
    return payload


def _envelope(route=None, *, audit_id="audit_1", server="duffel-flights"):
    envelope = build_tool_execution_envelope(
        tool_name="search_flights", arguments={}, source="mcp", server_name=server,
        audit_id=audit_id,
        result={"success": True, "provider": "duffel", "data_environment": "production", "routes": [route or _route()]},
        retrieved_at="2026-10-05T10:00:00+00:00",
    )
    envelope["metadata"]["evidence_allowed"] = True
    return envelope


def _parse(payload, envelopes=(), scopes=()):
    return parse_research_packet_output(
        json.dumps(payload), expected_worker="transport_researcher", expected_run_id="run_test",
        authoritative_tool_results=envelopes, required_route_scopes=scopes,
    )


def _numbers(packet):
    return [segment.service_number for segment in packet.candidates[0].segments]


def _invent_segment_fact(payload):
    candidate = payload["candidates"][0]
    candidate["segments"][0]["service_number"] = "XX999"
    candidate["constraint_evaluations"] = [{
        "constraint_id": "c1", "status": "passed", "fact_assertion_ids": ["invented"],
    }]
    entity = {"entity_type": "transport_leg", "entity_id": candidate["candidate_id"]}
    payload["fact_assertions"] = [{
        "fact_assertion_id": "invented", "entity_ref": entity, "field_path": "segments",
        "asserted_value": deepcopy(candidate["segments"]), "criticality": "execution_critical",
        "status": "verified", "source_links": [{
            "source_record_id": "fabricated", "relation": "supports", "source_locator": "anything",
        }],
    }]
    payload["field_provenance"] = [{
        "origin": "external_fact", "entity_ref": entity,
        "field_path": "segments", "reference_ids": ["invented"],
    }]


def test_restores_each_selected_segment_and_builds_exact_fact_lineage():
    scope = _scope()
    payload = _payload(scope=scope)
    _invent_segment_fact(payload)
    payload["candidates"][0]["segments"][1]["service_number"] = None
    packet = _parse(payload, [_envelope()], [scope])

    candidate = packet.candidates[0]
    assert _numbers(packet) == ["NH920", "NH221"]
    assert candidate.route_id == "duffel:offer_1"
    assert candidate.provider_evidence_scope_id == scope.scope_id
    assert candidate.constraint_evaluations[0].status == "unknown"
    assert candidate.constraint_evaluations[0].fact_assertion_ids == []
    source_id = _provider_route_source_id("audit_1", candidate.route_id)
    assert candidate.source_record_ids == [source_id]
    assert [(fact.field_path, fact.asserted_value, fact.source_links[0].source_locator) for fact in packet.fact_assertions] == [
        ("segments[0].service_number", "NH920", "sanitized_result.routes[0].segments[0].service_number"),
        ("segments[1].service_number", "NH221", "sanitized_result.routes[0].segments[1].service_number"),
    ]
    assert all(fact.source_links[0].source_record_id == source_id for fact in packet.fact_assertions)
    assert all(item.reference_ids == [fact.fact_assertion_id] for item, fact in zip(packet.field_provenance, packet.fact_assertions))
    assert packet.source_records[0].snapshot["sanitized_result"]["routes"][0]["segments"][0]["service_number"] == "NH920"
    FactStoreSnapshot(
        fact_data_revision=packet.fact_data_revision, source_records=packet.source_records,
        fact_assertions=packet.fact_assertions, field_provenance=packet.field_provenance,
    )


async def test_worker_finalization_forwards_authoritative_route_scope():
    scope = _scope()
    packet = await parse_research_packet(
        json.dumps(_payload(scope=scope)), expected_worker="transport_researcher",
        expected_run_id="run_test", authoritative_tool_results=[_envelope()],
        required_route_scopes=[scope],
    )
    assert _numbers(packet) == ["NH920", "NH221"]


@pytest.mark.parametrize("has_scope", [True, False])
def test_verified_numbers_and_source_lineage_reach_materialized_transport(has_scope):
    scope = _scope(origin="osm:relation:shanghai", destination="osm:relation:tokyo")
    payload = _payload(scope=scope) if has_scope else _payload_with_no_scope()
    packet = _parse(payload, [_envelope()], [scope] if has_scope else [])
    candidate = packet.candidates[0]
    draft = itinerary_draft([{"placement_kind": "transport", "candidate_id": candidate.candidate_id}])
    draft["days"][0]["date"] = "2026-11-20"
    draft["days"][0]["destination_id"] = candidate.destination_id
    workspace = materialize_trip_workspace(
        run_id="run_test", workspace_revision=0,
        composition=parse_itinerary_composition(json.dumps(draft)),
        catalog=make_catalog(packet), requirements="", composition_mutations=[],
        user_input_anchors=[UserInputAnchor(
            anchor_id="destination",
            field_path=f"{CONTROLLED_DESTINATION_ANCHOR_PREFIX}{candidate.destination_id}",
            value={"place_id": candidate.destination_id, "name": "东京"},
            input_kind="controlled_identity",
        )],
    )
    leg = workspace.itinerary.transport_legs[0]
    assert [segment.service_number for segment in leg.segments] == ["NH920", "NH221"]
    assert leg.lineage.fact_assertion_ids == candidate.fact_assertion_ids
    assert leg.lineage.source_record_ids == candidate.source_record_ids
    assert workspace.recommendation_catalog.candidate_index()[candidate.candidate_id].provider_evidence_scope_id == (
        scope.scope_id if has_scope else None
    )
    facts = build_fact_snapshot(workspace)
    now = datetime(2026, 10, 5, 10, tzinfo=timezone.utc)
    weather = WeatherContextSnapshot(
        weather_data_revision=0, trip_start_date=date(2026, 11, 20),
        trip_end_date=date(2026, 11, 20), days=[], retrieved_at=now,
    )
    report, map_projection, source_index = build_delivery_projections(
        workspace, facts, weather, generated_at=now,
    )
    bundle = assemble_delivery_bundle(TravelAgentState(
        run_id="run_test", trip_workspace=workspace, fact_store_snapshot=facts,
        weather_context=weather, report_projection=report, map_projection=map_projection,
        source_index_projection=source_index,
    ))
    restored = DeliveryBundle.model_validate_json(bundle.model_dump_json())
    assert [segment.service_number for segment in restored.workspace.itinerary.transport_legs[0].segments] == ["NH920", "NH221"]
    assert {fact.field_path for fact in restored.fact_snapshot.fact_assertions} == {
        "segments[0].service_number", "segments[1].service_number",
    }
    public = public_delivery_bundle(restored)
    public_segments = public["workspace"]["itinerary"]["transport_legs"][0]["segments"]
    assert [segment["service_number"] for segment in public_segments] == ["NH920", "NH221"]
    assert {
        field_path for citation in public["source_index"]["content"]["citations"]
        for field_path in citation["field_paths"]
    } == {"segments[0].service_number", "segments[1].service_number"}


def test_city_scope_keeps_real_numbers_without_changing_scope_or_asserting_city_mapping():
    scope = _scope(origin="osm:relation:shanghai", destination="osm:relation:tokyo")
    payload = _payload(scope=scope)
    packet = _parse(payload, [_envelope()], [scope])
    assert _numbers(packet) == ["NH920", "NH221"]
    assert packet.candidates[0].provider_evidence_scope_id == scope.scope_id
    assert {fact.field_path for fact in packet.fact_assertions} == {
        "segments[0].service_number", "segments[1].service_number",
    }


async def test_worker_without_scope_keeps_only_exactly_verified_numbers():
    payload = _payload()
    payload["candidates"][0]["provider_evidence_scope_id"] = None
    _invent_segment_fact(payload)
    packet = await parse_research_packet(
        json.dumps(payload), expected_worker="transport_researcher", expected_run_id="run_test",
        authoritative_tool_results=[_envelope()],
    )
    assert _numbers(packet) == ["NH920", "NH221"]
    assert packet.candidates[0].provider_evidence_scope_id is None
    assert len(packet.fact_assertions) == 2
    assert packet.candidates[0].constraint_evaluations[0].status == "unknown"
    payload["candidates"][0]["segments"][0]["segment_id"] = "wrong"
    assert _numbers(_parse(payload, [_envelope()])) == [None, None]
    assert _numbers(_parse(_payload_with_no_scope(), [])) == [None, None]


def _payload_with_no_scope():
    payload = _payload()
    payload["candidates"][0]["provider_evidence_scope_id"] = None
    return payload


def test_generated_segment_id_can_be_bound_with_full_route_identity():
    scope = _scope()
    route = _route()
    route["segments"][0]["segment_id"] = "segment_1"
    route["segments"][1]["segment_id"] = "segment_2"
    payload = _payload(route=route, scope=scope)
    packet = _parse(payload, [_envelope(route)], [scope])
    assert _numbers(packet) == ["NH920", "NH221"]


def test_a_model_fact_cannot_reuse_a_provider_generated_fact_id():
    scope = _scope()
    payload = _payload(scope=scope)
    _invent_segment_fact(payload)
    fact_id = _provider_fact_id("audit_1", "visit_a", "segments[0].service_number")
    payload["fact_assertions"][0]["fact_assertion_id"] = fact_id
    payload["field_provenance"][0]["reference_ids"] = [fact_id]
    payload["candidates"][0]["constraint_evaluations"][0]["fact_assertion_ids"] = [fact_id]
    packet = _parse(payload, [_envelope()], [scope])
    assert _numbers(packet) == [None, None]
    assert packet.candidates[0].constraint_evaluations[0].status == "unknown"
    assert not packet.field_provenance


def test_missing_provider_number_is_not_filled_from_the_model():
    route = _route()
    route["segments"][1]["service_number"] = None
    payload = _payload(route)
    payload["candidates"][0]["segments"][1]["service_number"] = "XX999"
    scope = _scope()
    packet = _parse(payload, [_envelope(route)], [scope])

    assert _numbers(packet) == ["NH920", None]
    assert [fact.field_path for fact in packet.fact_assertions] == ["segments[0].service_number"]


@pytest.mark.parametrize("change", [
    "missing_scope", "unassigned_scope", "different_scope", "different_run", "different_run_unscoped",
    "wrong_origin", "wrong_destination",
    "wrong_date", "cross_day", "unknown_route", "wrong_server", "wrong_provider",
    "wrong_tool", "failed", "quarantined", "not_allowed", "missing_audit", "reference_only",
    "segment_id", "duplicate_segment_id", "segment_order", "segment_time", "segment_endpoint",
    "missing_segment_time", "route_time", "route_timezone", "segment_timezone",
    "missing_endpoint_code", "invalid_provider_number",
])
def test_flight_number_is_removed_when_identity_or_evidence_is_not_exact(change):
    scope = _scope()
    payload = _payload(scope=scope)
    _invent_segment_fact(payload)
    envelope = _envelope()
    scopes = [scope]
    candidate = payload["candidates"][0]
    route = envelope["sanitized_result"]["routes"][0]
    if change == "missing_scope":
        scopes = []
    elif change == "unassigned_scope":
        candidate["provider_evidence_scope_id"] = None
    elif change == "different_scope":
        candidate["provider_evidence_scope_id"] = "a" * 64
    elif change in {"different_run", "different_run_unscoped"}:
        scopes = [_scope(run_id="other_run")]
        candidate["provider_evidence_scope_id"] = (
            scopes[0].scope_id if change == "different_run" else None
        )
    elif change in {"wrong_origin", "wrong_destination", "wrong_date", "cross_day"}:
        kwargs = {
            "wrong_origin": {"origin": "iata:SHA"},
            "wrong_destination": {"destination": "iata:NRT"},
            "wrong_date": {"day": date(2026, 11, 21)},
            "cross_day": {"cross_day": True},
        }[change]
        scopes = [_scope(**kwargs)]
        candidate["provider_evidence_scope_id"] = scopes[0].scope_id
    elif change == "unknown_route":
        candidate["route_id"] = "duffel:other"
    elif change == "wrong_server":
        envelope["server_name"] = "other"
    elif change == "wrong_provider":
        envelope["sanitized_result"]["provider"] = "other"
    elif change == "wrong_tool":
        envelope["tool_name"] = "global_route_search"
    elif change == "failed":
        envelope["status"] = "failed"
    elif change == "reference_only":
        envelope["status"] = "reference_only"
    elif change == "quarantined":
        envelope["metadata"]["quarantine_result"] = True
    elif change == "not_allowed":
        envelope["metadata"]["evidence_allowed"] = False
    elif change == "missing_audit":
        envelope["audit_id"] = ""
    elif change == "segment_id":
        candidate["segments"][0]["segment_id"] = "another"
    elif change == "duplicate_segment_id":
        candidate["segments"][1]["segment_id"] = candidate["segments"][0]["segment_id"]
        route["segments"][1]["segment_id"] = route["segments"][0]["segment_id"]
    elif change == "segment_order":
        candidate["segments"][0]["segment_id"], candidate["segments"][1]["segment_id"] = (
            candidate["segments"][1]["segment_id"], candidate["segments"][0]["segment_id"]
        )
    elif change == "segment_time":
        candidate["segments"][1]["departure_at"] = "2026-11-20T15:01:00+09:00"
    elif change == "segment_endpoint":
        candidate["segments"][1]["from_endpoint"] = _endpoint("KIX")
    elif change == "missing_segment_time":
        candidate["segments"][1]["departure_at"] = None
    elif change == "route_time":
        candidate["arrival_at"] = "2026-11-20T16:01:00+09:00"
    elif change == "route_timezone":
        candidate["departure_at"] = "2026-11-20T01:00:00+00:00"
    elif change == "segment_timezone":
        candidate["segments"][0]["departure_at"] = "2026-11-20T01:00:00+00:00"
    elif change == "missing_endpoint_code":
        candidate["segments"][0]["from_endpoint"].pop("station_code")
        candidate["from_endpoint"].pop("station_code")
    elif change == "invalid_provider_number":
        for segment in route["segments"]:
            segment["service_number"] = "not a flight number"
    packet = _parse(payload, [envelope], scopes)

    assert _numbers(packet) == [None, None]
    assert all(not fact.field_path.startswith("segments") for fact in packet.fact_assertions)
    assert packet.candidates[0].constraint_evaluations[0].status == "unknown"


def test_conflicting_route_ids_are_ambiguous_but_unrelated_records_cannot_replace_them():
    scope = _scope()
    payload = _payload(scope=scope)
    first = _envelope()
    conflicting = deepcopy(first)
    conflicting["audit_id"] = "audit_2"
    conflicting["sanitized_result"]["routes"][0]["segments"][0]["service_number"] = "CA123"
    assert _numbers(_parse(deepcopy(payload), [first, conflicting], [scope])) == [None, None]
    malformed = deepcopy(conflicting)
    malformed["sanitized_result"]["routes"][0]["segments"] = []
    assert _numbers(_parse(deepcopy(payload), [first, malformed], [scope])) == [None, None]
    conflicting["server_name"] = "unrelated-server"
    assert _numbers(_parse(deepcopy(payload), [first, conflicting], [scope])) == ["NH920", "NH221"]
    identical = deepcopy(first)
    identical["audit_id"] = "audit_3"
    packet = _parse(deepcopy(payload), [first, identical], [scope])
    assert _numbers(packet) == ["NH920", "NH221"]
    assert packet.source_records[0].tool_audit_id == "audit_3"


def test_conflicting_audit_identity_cannot_bind_or_borrow_source():
    scope = _scope()
    first = _envelope()
    second = _envelope(audit_id="audit_1", server="unrelated-server")
    assert _numbers(_parse(_payload(scope=scope), [first, second], [scope])) == [None, None]


def test_strict_collision_check_does_not_change_existing_route_selection():
    first = _envelope()
    second = deepcopy(first)
    second["audit_id"] = "audit_2"
    second["sanitized_result"]["routes"][0]["segments"][0]["service_number"] = "CA123"
    messages = authoritative_tool_messages([first, second])
    assert _successful_route_records(messages)["duffel:offer_1"][0]["audit_id"] == "audit_2"
    assert _successful_route_records(messages, reject_conflicting_ids=True) == {}


def test_cached_source_locator_points_into_actual_provider_snapshot():
    scope = _scope()
    envelope = _envelope()
    envelope["metadata"]["snapshot_cache"] = {
        "origin": "provider_snapshot_cache", "observed_at": "2026-10-05T09:00:00+00:00",
        "retrieved_at": "2026-10-05T10:00:00+00:00", "cache_valid_until": "2026-10-06T10:00:00+00:00",
        "cache_key_digest": "a" * 64, "content_hash": "b" * 64, "contract_version": "1",
    }
    packet = _parse(_payload(scope=scope), [envelope], [scope])
    source = packet.source_records[0]
    assert source.cache_provenance is not None
    assert source.content_hash == "b" * 64
    assert source.snapshot["routes"][0]["segments"][0]["service_number"] == "NH920"
    assert packet.fact_assertions[0].source_links[0].source_locator == "routes[0].segments[0].service_number"


@pytest.mark.parametrize("mode", ["train", "high_speed_rail", "metro", "bus"])
def test_nonflight_transport_numbers_and_facts_are_unaffected(mode):
    payload = _payload()
    candidate = payload["candidates"][0]
    candidate["selected_mode"] = mode
    candidate["transport_class"] = "long_distance" if mode in {"train", "high_speed_rail"} else "public_transit"
    if candidate["transport_class"] != "long_distance":
        candidate["provider_evidence_scope_id"] = None
    for segment in candidate["segments"]:
        segment["mode"] = mode
        segment["service_number"] = "G123"
    packet = _parse(payload)
    assert _numbers(packet) == ["G123", "G123"]


def test_no_new_candidate_or_scope_is_created_from_provider_routes():
    scope = _scope()
    payload = _payload(scope=scope)
    payload["candidates"] = []
    packet = _parse(payload, [_envelope()], [scope])
    assert packet.candidates == []
    assert packet.fact_assertions == []
