"""Exact-argument operation manifests for an already approved research plan.

This is a deterministic primitive, not an authorization source: callers must load
its manifest from server-owned state, validate the final plan approval and live
lease, and run the check before provider calls, fallback adapters or cache reads.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional

from pydantic import Field, model_validator

from travel_agent.schema import StrictModel


_OPERATION_VERSION = "journeypilot.research_operation.v1"
_MAX_ARGUMENT_CHARS = 12000
_MAX_OPERATIONS = 256
_HASH_PATTERN = r"^[0-9a-f]{64}$"


def _json_arguments(arguments: Dict[str, Any]) -> str:
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments must be an object")

    def validate(value: Any, depth: int) -> None:
        if depth > 32:
            raise ValueError("tool arguments are too deeply nested")
        if isinstance(value, dict):
            if not all(isinstance(key, str) for key in value):
                raise ValueError("tool argument keys must be strings")
            for nested in value.values():
                validate(nested, depth + 1)
        elif isinstance(value, list):
            for nested in value:
                validate(nested, depth + 1)
        elif value is not None and not isinstance(value, (str, bool, int, float)):
            raise ValueError("tool arguments must contain JSON values")

    validate(arguments, 0)
    try:
        encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        encoded.encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("tool arguments must be finite JSON") from exc
    if len(encoded) > _MAX_ARGUMENT_CHARS:
        raise ValueError("tool arguments exceed the operation limit")
    return encoded


def _operation_digest(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class AuthorizedToolOperation(StrictModel):
    operation_id: str = Field(pattern=r"^operation_[0-9a-f]{24}$")
    tool_name: str = Field(min_length=1, max_length=100)
    query_id: str = Field(min_length=1, max_length=128)
    arguments_json: str = Field(min_length=2, max_length=_MAX_ARGUMENT_CHARS)
    fallback_after_query_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=40)
    parent_evidence_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=40)

    @model_validator(mode="after")
    def validate_integrity(self) -> "AuthorizedToolOperation":
        try:
            arguments = json.loads(self.arguments_json)
        except (ValueError, TypeError) as exc:
            raise ValueError("operation arguments are invalid JSON") from exc
        if _json_arguments(arguments) != self.arguments_json:
            raise ValueError("operation arguments must be canonical")
        if len(set(self.fallback_after_query_ids)) != len(self.fallback_after_query_ids):
            raise ValueError("fallback dependencies must be unique")
        if len(set(self.parent_evidence_ids)) != len(self.parent_evidence_ids):
            raise ValueError("parent evidence ids must be unique")
        material = self.model_dump(mode="json", exclude={"operation_id"})
        if self.operation_id != "operation_" + _operation_digest(material)[:24]:
            raise ValueError("operation id does not match its parameters")
        return self


def canonical_operation_arguments(arguments: Dict[str, Any]) -> str:
    """Return the canonical JSON form used for exact operation matching."""
    return _json_arguments(arguments)


def research_approval_confirmation_hash(
    request_contract_hash: str, approval_token: str,
) -> str:
    if len(request_contract_hash) != 64 or not approval_token:
        raise ValueError("plan approval requires a contract hash and version token")
    return _operation_digest({
        "schema_version": "journeypilot.research_plan_approval.v1",
        "request_contract_hash": request_contract_hash,
        "approval_token": approval_token,
    })


def build_authorized_operation(
    *, tool_name: str, query_id: str, arguments: Dict[str, Any],
    fallback_after_query_ids: tuple[str, ...] = (), parent_evidence_ids: tuple[str, ...] = (),
) -> AuthorizedToolOperation:
    """Construct from server-compiled parameters, never from model-supplied args."""
    material = {
        "tool_name": tool_name,
        "query_id": query_id,
        "arguments_json": _json_arguments(arguments),
        "fallback_after_query_ids": list(fallback_after_query_ids),
        "parent_evidence_ids": list(parent_evidence_ids),
    }
    return AuthorizedToolOperation(
        operation_id="operation_" + _operation_digest(material)[:24], **material,
    )


class ApprovedOperationManifest(StrictModel):
    version: str = _OPERATION_VERSION
    run_id: str = Field(min_length=1, max_length=128)
    generation_id: str = Field(min_length=1, max_length=128)
    identity_hash: str = Field(pattern=_HASH_PATTERN)
    confirmation_hash: str = Field(pattern=_HASH_PATTERN)
    query_plan_hash: str = Field(pattern=_HASH_PATTERN)
    approval_token: str = Field(min_length=1, max_length=200)
    manifest_hash: str = Field(default="", pattern=r"^(?:|[0-9a-f]{64})$")
    operations: tuple[AuthorizedToolOperation, ...] = Field(min_length=1, max_length=_MAX_OPERATIONS)

    @model_validator(mode="after")
    def validate_manifest(self) -> "ApprovedOperationManifest":
        if self.version != _OPERATION_VERSION:
            raise ValueError("unsupported operation manifest version")
        ids = [item.operation_id for item in self.operations]
        if len(ids) != len(set(ids)):
            raise ValueError("operation ids must be unique")
        # The plan approval must bind this digest. The approval token itself is
        # excluded to avoid a circular dependency when constructing the gate.
        material = self.model_dump(mode="json", exclude={"manifest_hash", "approval_token"})
        expected = _operation_digest(material)
        if self.manifest_hash and self.manifest_hash != expected:
            raise ValueError("operation manifest hash does not match its contents")
        object.__setattr__(self, "manifest_hash", expected)
        return self


class OperationApproval(StrictModel):
    """服务端独立保存的批准记录。

    执行时必须只从这里读取 ``approved_manifest_hash``，不能从当前 manifest
    重新推导；否则被替换后重新计算 hash 的 manifest 会自我批准。
    """

    version: str = "journeypilot.research_operation_approval.v1"
    run_id: str = Field(min_length=1, max_length=128)
    generation_id: str = Field(min_length=1, max_length=128)
    identity_hash: str = Field(pattern=_HASH_PATTERN)
    confirmation_hash: str = Field(pattern=_HASH_PATTERN)
    query_plan_hash: str = Field(pattern=_HASH_PATTERN)
    approval_token: str = Field(min_length=1, max_length=200)
    approved_manifest_hash: str = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_version(self) -> "OperationApproval":
        if self.version != "journeypilot.research_operation_approval.v1":
            raise ValueError("unsupported operation approval version")
        return self


def build_operation_approval(
    *, manifest: ApprovedOperationManifest, approval_token: Optional[str] = None,
) -> OperationApproval:
    """批准时由服务端构造；token 必须与 manifest 中的计划版本一致。"""
    token = manifest.approval_token if approval_token is None else approval_token
    if token != manifest.approval_token:
        raise ValueError("operation approval token does not match the manifest")
    return OperationApproval(
        run_id=manifest.run_id,
        generation_id=manifest.generation_id,
        identity_hash=manifest.identity_hash,
        confirmation_hash=manifest.confirmation_hash,
        query_plan_hash=manifest.query_plan_hash,
        approval_token=token,
        approved_manifest_hash=manifest.manifest_hash,
    )


def operation_is_authorized(
    manifest: ApprovedOperationManifest, *, operation_id: str, tool_name: str,
    arguments: Dict[str, Any], run_id: str, generation_id: str, identity_hash: str,
    confirmation_hash: str, query_plan_hash: str, approval_token: str,
    approved_manifest_hash: str, live_lease: bool,
    authorized_query_ids: set[str], executed_query_ids: set[str],
    authorized_evidence_ids: set[str],
) -> bool:
    """Fail closed on stale scope, hidden parameters or unfulfilled prerequisites.

    ``approved_manifest_hash`` must come from the persisted server approval,
    never from the requesting model or client.
    """
    try:
        manifest = ApprovedOperationManifest.model_validate(manifest.model_dump(mode="json"))
    except (TypeError, ValueError):
        return False
    if (
        live_lease is not True
        or not all(isinstance(item, (set, frozenset)) for item in (
            authorized_query_ids, executed_query_ids, authorized_evidence_ids,
        ))
    ):
        return False
    if manifest.manifest_hash != approved_manifest_hash or (
        manifest.run_id != run_id
        or manifest.generation_id != generation_id
        or manifest.identity_hash != identity_hash
        or manifest.confirmation_hash != confirmation_hash
        or manifest.query_plan_hash != query_plan_hash
        or manifest.approval_token != approval_token
    ):
        return False
    operation: Optional[AuthorizedToolOperation] = next(
        (item for item in manifest.operations if item.operation_id == operation_id), None,
    )
    if operation is None or operation.tool_name != tool_name:
        return False
    if operation.query_id not in authorized_query_ids:
        return False
    if not set(operation.fallback_after_query_ids) <= executed_query_ids:
        return False
    if not set(operation.parent_evidence_ids) <= authorized_evidence_ids:
        return False
    try:
        return _json_arguments(arguments) == operation.arguments_json
    except ValueError:
        return False
