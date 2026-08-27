"""Identity-facts failure routing for the Research Packet schema gate.

``parse_research_packet_output`` may rewrite a candidate-bearing packet to a
zero-candidate packet (keeping the provider failure record for the next
Candidate Gate round) only when two conditions hold together: the schema
failure is the "no eligible identity-bound facts" rejection, and the server's
own transcript recorded a failed tool source.  These tests pin that the first
condition is decided by the structured validation error type raised in
``delivery_bundle.ResearchPacket``, never by text that appears in
``str(ValidationError)`` — model-authored payload is echoed into that string,
so a substring match there is an injection surface.
"""

import json
import logging

import pytest

from travel_agent.agents.research_packet_output import (
    ResearchPacketOutputError,
    parse_research_packet_output,
)
from travel_agent.entities.delivery_bundle import ResearchPacket, SourceRecord

_PACKET_LOGGER = "travel_agent.agents.research_packet_output"
_IDENTITY_FACTS_MESSAGE = "research packet requires external identity-bound facts"
_CLOSURE_DROPPED_LOG = "Research Packet candidate closure dropped"
_RUN_ID = "run-1"
_GENERATED_AT = "2026-08-26T12:00:00+00:00"
_COMPILED_SOURCE_ID = "external_tool:audit-1:deadbeef"


def _compiled_source(*, lifecycle_status: str) -> SourceRecord:
    """A server-compiled tool source for this round's transcript."""

    return SourceRecord.model_validate(
        {
            "source_record_id": _COMPILED_SOURCE_ID,
            "source_kind": "external_tool",
            "title": "global_place_search failed",
            "provider_name": "amap",
            "public_excerpt": "provider degraded",
            "retrieved_at": _GENERATED_AT,
            "content_hash": "a" * 64,
            "snapshot": {"error": "provider degraded"},
            "lifecycle_status": lifecycle_status,
            "tool_audit_id": "audit-1",
        }
    )


def _candidate_bearing_packet_payload(**extra_fields: object) -> dict:
    """A packet payload that passes every field-level check and then trips the
    identity-facts model validator: it carries one candidate but no fact that
    could survive normalization (no fact assertions at all)."""

    return {
        "research_packet_id": "rp-1",
        "run_id": _RUN_ID,
        "generation_id": "gen-1",
        "intent_spec_revision": 1,
        "research_query_plan_id": "plan-1",
        "executed_query_ids": ["q-1"],
        "task_id": "task-1",
        "worker_kind": "destination_researcher",
        "constraint_pack_revision": 0,
        "fact_data_revision": 0,
        "query_context": {
            "research_round": 0,
            "query_lineage": [
                {"query_id": "q-1", "domain": "visit", "query_kind": "structural"}
            ],
        },
        "candidates": [
            {
                "candidate_kind": "visit",
                "candidate_id": "cand-1",
                "research_packet_id": "rp-1",
                "destination_id": "dest-1",
                "fact_assertion_ids": ["fact-1"],
                "source_record_ids": [_COMPILED_SOURCE_ID],
                "field_paths": ["name"],
                "weather_sensitivity": {
                    "exposure": "indoor",
                    "rain_sensitivity": "none",
                    "heat_sensitivity": "none",
                    "cold_sensitivity": "none",
                    "wind_sensitivity": "none",
                    "requires_clear_visibility": False,
                },
                "selection_reasons": [
                    "only candidate in the closure",
                    "indoor fallback",
                ],
                "tradeoff": "single grounded option",
                "freshness_status": "stale",
                "place_id": "place-1",
                "provider_place_type": "museum",
                "provider_country_code": "JP",
                "name": "Example Museum",
                "address": "1-2 Example, Tokyo",
                "visit_type": "culture",
                "recommended_duration_minutes": 90,
            }
        ],
        "fact_assertions": [],
        "field_provenance": [],
        "generated_at": _GENERATED_AT,
        **extra_fields,
    }


def _parse(payload: dict, **kwargs: object) -> ResearchPacket:
    return parse_research_packet_output(
        json.dumps(payload),
        expected_worker="destination_researcher",
        expected_run_id=_RUN_ID,
        **kwargs,
    )


def _closure_dropped(caplog: pytest.LogCaptureFixture) -> bool:
    return any(_CLOSURE_DROPPED_LOG in record.message for record in caplog.records)


def test_identity_facts_missing_with_failed_source_takes_the_rewrite_branch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Error code + server-recorded failed source → the zero-candidate rewrite
    branch is taken (its dedicated warning fires; the direct schema-gate refusal
    never logs it)."""

    with caplog.at_level(logging.WARNING, logger=_PACKET_LOGGER):
        with pytest.raises(ResearchPacketOutputError):
            _parse(
                _candidate_bearing_packet_payload(),
                authoritative_source_records=[
                    _compiled_source(lifecycle_status="rejected")
                ],
            )
    assert _closure_dropped(caplog)


def test_identity_facts_missing_without_failed_source_raises_schema_gate_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Same structured error, but the transcript holds no rejected source: the
    rewrite is not authorized and the packet is refused outright."""

    with caplog.at_level(logging.WARNING, logger=_PACKET_LOGGER):
        with pytest.raises(ResearchPacketOutputError):
            _parse(
                _candidate_bearing_packet_payload(),
                authoritative_source_records=[
                    _compiled_source(lifecycle_status="active")
                ],
            )
    assert not _closure_dropped(caplog)


def _validation_error_text(payload: dict) -> str:
    try:
        ResearchPacket.model_validate(payload)
    except Exception as exc:  # pydantic ValidationError
        return str(exc)
    raise AssertionError("payload was expected to fail validation")


def test_injected_literal_reaches_str_of_error_but_not_the_rewrite_branch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Injection surface: model-authored text reaches str(ValidationError) via
    input echoes, so a payload naming the identity-facts message must not
    satisfy the rewrite condition.  The literal rides in as a forbidden extra
    key, which the error rendering echoes verbatim — a substring check on
    str(exc) takes the rewrite branch here; the structured error type does not."""

    payload = _candidate_bearing_packet_payload(**{_IDENTITY_FACTS_MESSAGE: "x"})
    assert _IDENTITY_FACTS_MESSAGE in _validation_error_text(payload)
    with caplog.at_level(logging.WARNING, logger=_PACKET_LOGGER):
        with pytest.raises(ResearchPacketOutputError):
            _parse(
                payload,
                authoritative_source_records=[
                    _compiled_source(lifecycle_status="rejected")
                ],
            )
    assert not _closure_dropped(caplog)


def test_genuine_identity_facts_failure_still_routes_and_keeps_its_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Control for the injection test: the error genuinely raised by the
    identity-facts validator still routes to the rewrite branch, and its
    human-readable message survives into the raised error for logs."""

    with caplog.at_level(logging.WARNING, logger=_PACKET_LOGGER):
        with pytest.raises(ResearchPacketOutputError) as excinfo:
            _parse(
                _candidate_bearing_packet_payload(),
                authoritative_source_records=[
                    _compiled_source(lifecycle_status="rejected")
                ],
            )
    assert _closure_dropped(caplog)
    assert _IDENTITY_FACTS_MESSAGE in str(excinfo.value)
