"""研究成果中可确定的类型缺漏不应丢弃整份数据。"""

import json
from datetime import datetime, timezone

import pytest

from tests.fixtures.research_packets import make_packet
from travel_agent.planning.research.output.metadata import build_authoritative_research_packet_metadata
from travel_agent.planning.research.output.parsing import parse_research_packet_output
from travel_agent.planning.research.output.policy import ResearchPacketOutputError
from travel_agent.tools.governance import build_tool_execution_envelope


def _payload(worker="destination_researcher"):
    payload = make_packet(worker=worker).model_dump(mode="json")
    payload.update(source_records=[], fact_assertions=[], field_provenance=[])
    candidate = payload["candidates"][0]
    candidate.pop("candidate_kind")
    candidate.update(fact_assertion_ids=[], source_record_ids=[], field_paths=[])
    return payload


@pytest.mark.parametrize(
    ("worker", "kind"),
    [
        ("destination_researcher", "visit"),
        ("accommodation_researcher", "lodging"),
        ("transport_researcher", "transport"),
    ],
)
def test_missing_kind_and_medium_weather_are_retained(worker, kind):
    payload = _payload(worker)
    sensitivity = payload["candidates"][0]["weather_sensitivity"]
    sensitivity.update(cold_sensitivity="medium", wind_sensitivity="medium")

    packet = parse_research_packet_output(
        json.dumps(payload), expected_worker=worker, expected_run_id="run_test"
    )

    candidate = packet.candidates[0]
    assert candidate.candidate_kind == kind
    assert candidate.weather_sensitivity.cold_sensitivity == "medium"
    assert candidate.weather_sensitivity.wind_sensitivity == "medium"
    assert candidate.candidate_id == "visit_a"


def test_missing_dining_kind_is_distinguished_from_visit():
    payload = _payload()
    candidate = payload["candidates"][0]
    candidate["branch_name"] = candidate.pop("name")
    candidate.pop("visit_type")
    candidate.pop("recommended_duration_minutes")
    candidate.pop("estimated_cost_cny")
    candidate.pop("highlights")
    candidate.update(meal_types=["lunch"], availability_status="needs_confirmation")

    packet = parse_research_packet_output(
        json.dumps(payload), expected_worker="destination_researcher", expected_run_id="run_test"
    )

    assert packet.candidates[0].candidate_kind == "dining"


@pytest.mark.parametrize("kind", [None, "unknown"])
def test_ambiguous_or_invalid_kind_is_not_guessed(kind):
    payload = _payload()
    candidate = payload["candidates"][0]
    candidate["branch_name"] = "另一种候选类型的字段"
    if kind is not None:
        candidate["candidate_kind"] = kind

    with pytest.raises(ResearchPacketOutputError):
        parse_research_packet_output(
            json.dumps(payload), expected_worker="destination_researcher", expected_run_id="run_test"
        )


def test_unobserved_tool_sources_and_their_facts_do_not_survive():
    payload = make_packet().model_dump(mode="json")
    payload["candidates"][0].pop("candidate_kind")

    packet = parse_research_packet_output(
        json.dumps(payload), expected_worker="destination_researcher", expected_run_id="run_test"
    )

    assert packet.candidates[0].candidate_kind == "visit"
    assert packet.source_records == []
    assert packet.fact_assertions == []
    assert packet.field_provenance == []


def test_tool_source_snapshot_is_taken_from_the_observed_call():
    payload = make_packet().model_dump(mode="json")
    payload["candidates"][0].pop("candidate_kind")
    payload["source_records"][0]["snapshot"] = {"fabricated": "model text"}
    result = {"success": True, "name": "Museum visit_a", "provider": "fixture"}
    envelope = build_tool_execution_envelope(
        tool_name="lookup", arguments={}, result=result, audit_id="audit_visit_a"
    )
    envelope["metadata"]["evidence_allowed"] = True

    packet = parse_research_packet_output(
        json.dumps(payload), expected_worker="destination_researcher", expected_run_id="run_test",
        authoritative_tool_results=[envelope],
    )

    assert packet.source_records[0].snapshot["sanitized_result"] == result
    assert packet.candidates[0].source_record_ids == [packet.source_records[0].source_record_id]
    assert packet.fact_assertions


def test_failed_tool_record_cannot_support_a_fact():
    payload = make_packet().model_dump(mode="json")
    failure_id = "source_tool_failure_audit_visit_a"
    payload["source_records"][0]["source_record_id"] = failure_id
    for fact in payload["fact_assertions"]:
        for link in fact["source_links"]:
            link["source_record_id"] = failure_id
    envelope = build_tool_execution_envelope(
        tool_name="lookup", arguments={}, status="failed", error="查询失败",
        audit_id="audit_visit_a",
    )

    packet = parse_research_packet_output(
        json.dumps(payload), expected_worker="destination_researcher", expected_run_id="run_test",
        authoritative_tool_results=[envelope],
    )

    assert packet.fact_assertions == []
    assert [source.lifecycle_status for source in packet.source_records] == ["rejected"]


def test_a_verified_fact_without_any_source_is_dropped_and_the_packet_survives():
    payload = make_packet(worker="accommodation_researcher").model_dump(mode="json")
    candidate = payload["candidates"][0]
    unsourced = {
        "fact_assertion_id": "fact_check_in",
        "entity_ref": {"entity_type": "lodging_stay", "entity_id": candidate["candidate_id"]},
        "field_path": "check_in_date",
        "asserted_value": "2026-11-09",
        "unit": None,
        "currency": None,
        "criticality": "execution_critical",
        "status": "verified",
        "observed_at": None,
        "effective_from": None,
        "effective_to": None,
        "expires_at": None,
        "source_links": [],
        "supersedes_assertion_ids": [],
    }
    payload["fact_assertions"].append(unsourced)
    payload["field_provenance"].append({
        "origin": "user_input",
        "entity_ref": unsourced["entity_ref"],
        "field_path": "check_in_date",
        "reference_ids": ["fact_check_in"],
    })
    candidate["fact_assertion_ids"] = [*candidate["fact_assertion_ids"], "fact_check_in"]

    packet = parse_research_packet_output(
        json.dumps(payload), expected_worker="accommodation_researcher", expected_run_id="run_test"
    )

    kept = {fact.fact_assertion_id for fact in packet.fact_assertions}
    assert "fact_check_in" not in kept
    assert "fact_check_in" not in packet.candidates[0].fact_assertion_ids
    assert all("fact_check_in" not in item.reference_ids for item in packet.field_provenance)


def _transport_payload_without_destination():
    payload = make_packet(worker="transport_researcher").model_dump(mode="json")
    for candidate in payload["candidates"]:
        candidate.pop("destination_id", None)
    return payload


def _metadata(destinations):
    return build_authoritative_research_packet_metadata(
        worker_kind="transport_researcher",
        run_id="run_test",
        generation_id="generation_test",
        task_id="transport_researcher",
        fact_data_revision=1,
        query_context={"controlled_trip_identity": {"destinations": destinations}},
        generated_at=datetime(2026, 10, 5, 10, tzinfo=timezone.utc),
    )


def test_a_missing_destination_id_is_taken_from_the_only_trip_destination():
    packet = parse_research_packet_output(
        json.dumps(_transport_payload_without_destination()),
        expected_worker="transport_researcher",
        expected_run_id="run_test",
        authoritative_packet_metadata=_metadata([{"place_id": "osm:relation:4430941"}]),
    )

    assert {item.destination_id for item in packet.candidates} == {"osm:relation:4430941"}


def test_a_missing_destination_id_is_not_guessed_for_a_multi_destination_trip():
    with pytest.raises(ResearchPacketOutputError):
        parse_research_packet_output(
            json.dumps(_transport_payload_without_destination()),
            expected_worker="transport_researcher",
            expected_run_id="run_test",
            authoritative_packet_metadata=_metadata([{"place_id": "a"}, {"place_id": "b"}]),
        )


def test_a_destination_id_the_model_provided_is_never_replaced():
    payload = make_packet(worker="transport_researcher").model_dump(mode="json")
    provided = payload["candidates"][0]["destination_id"]

    packet = parse_research_packet_output(
        json.dumps(payload),
        expected_worker="transport_researcher",
        expected_run_id="run_test",
        authoritative_packet_metadata=_metadata([{"place_id": "osm:relation:4430941"}]),
    )

    assert packet.candidates[0].destination_id == provided

