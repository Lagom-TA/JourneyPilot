"""Exact approved provider parameters; no provider or storage access."""

import pytest
from pydantic import ValidationError

from travel_agent.planning.research.operation_authority import (
    ApprovedOperationManifest, build_authorized_operation, operation_is_authorized,
)


HASHES = {"identity_hash": "a" * 64, "confirmation_hash": "b" * 64, "query_plan_hash": "c" * 64}


def setup_operation():
    operation = build_authorized_operation(
        tool_name="maps_text_search", query_id="query-dining-hz",
        arguments={"city": "杭州", "keywords": "素食", "aliases": ["素食"]},
        fallback_after_query_ids=("query-primary-hz",), parent_evidence_ids=("evidence-hz",),
    )
    manifest = ApprovedOperationManifest(
        run_id="run-1", generation_id="generation-1", approval_token="plan-version-1",
        operations=(operation,), **HASHES,
    )
    call = {
        "operation_id": operation.operation_id, "tool_name": "maps_text_search",
        "arguments": {"city": "杭州", "keywords": "素食", "aliases": ["素食"]},
        "run_id": "run-1", "generation_id": "generation-1", "approval_token": "plan-version-1",
        "approved_manifest_hash": manifest.manifest_hash,
        "live_lease": True, "authorized_query_ids": {"query-dining-hz"},
        "executed_query_ids": {"query-primary-hz"}, "authorized_evidence_ids": {"evidence-hz"},
        **HASHES,
    }
    return manifest, call


def test_exact_approved_operation_is_allowed():
    manifest, call = setup_operation()
    assert operation_is_authorized(manifest, **call)
    # Dict key order is not semantically significant.
    call["arguments"] = {"aliases": ["素食"], "keywords": "素食", "city": "杭州"}
    assert operation_is_authorized(manifest, **call)


@pytest.mark.parametrize("override", [
    {"arguments": {"city": "杭州", "keywords": "素食", "aliases": ["素食", "牛肉"]}},
    {"arguments": {"city": "苏州", "keywords": "素食", "aliases": ["素食"]}},
    {"arguments": {"city": "杭州", "keywords": "素食", "aliases": ["素食"], "extra": True}},
    {"tool_name": "free_web_search"},
    {"operation_id": "operation_" + "f" * 24},
    {"approval_token": "old-plan"},
    {"approved_manifest_hash": "0" * 64},
    {"run_id": "other-run"},
    {"generation_id": "old-generation"},
    {"identity_hash": "d" * 64},
    {"confirmation_hash": "e" * 64},
    {"query_plan_hash": "f" * 64},
    {"live_lease": False},
    {"authorized_query_ids": set()},
    {"executed_query_ids": set()},
    {"authorized_evidence_ids": set()},
])
def test_unapproved_parameter_or_stale_authority_is_rejected(override):
    manifest, call = setup_operation()
    assert not operation_is_authorized(manifest, **{**call, **override})


def test_operation_digest_cannot_be_reused_for_modified_arguments():
    manifest, _call = setup_operation()
    payload = manifest.operations[0].model_dump(mode="json")
    payload["arguments_json"] = '{"aliases":["素食"],"city":"苏州","keywords":"素食"}'
    with pytest.raises(ValidationError):
        type(manifest.operations[0]).model_validate(payload)


def test_model_copy_cannot_replace_hidden_arguments_after_approval():
    manifest, call = setup_operation()
    poisoned_args = {"city": "杭州", "keywords": "牛肉", "aliases": ["牛肉"]}
    poisoned_operation = manifest.operations[0].model_copy(update={
        "arguments_json": '{"aliases":["牛肉"],"city":"杭州","keywords":"牛肉"}',
    })
    poisoned_manifest = manifest.model_copy(update={"operations": (poisoned_operation,)})
    assert not operation_is_authorized(poisoned_manifest, **{**call, "arguments": poisoned_args})


def test_non_json_and_nonfinite_parameters_are_refused():
    with pytest.raises(ValueError):
        build_authorized_operation(tool_name="search", query_id="q1", arguments={"x": float("nan")})
    with pytest.raises(ValueError):
        build_authorized_operation(tool_name="search", query_id="q1", arguments={"x": object()})
    with pytest.raises(ValueError):
        build_authorized_operation(tool_name="search", query_id="q1", arguments={1: "not a string key"})
    with pytest.raises(ValueError):
        build_authorized_operation(tool_name="search", query_id="q1", arguments={"x": "\ud800"})
