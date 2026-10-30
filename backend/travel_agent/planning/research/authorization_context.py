"""Execution-time enforcement for approved research Provider operations.

The manifest is compiled and approved at the plan gate. This module only
compares the current assignment and the independent server approval with the
operation the worker is about to execute; it never derives authority from the
model's tool arguments.
"""

from __future__ import annotations

import contextvars
import datetime
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

from travel_agent.planning.assignments import resolve_agent_assignment
from travel_agent.planning.nodes import RESEARCH_WORKER_NODES
from travel_agent.planning.requirements.intent_contracts import canonical_json_hash
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.operation_authority import (
    ApprovedOperationManifest,
    AuthorizedToolOperation,
    OperationApproval,
    canonical_operation_arguments,
    operation_is_authorized,
    research_approval_confirmation_hash,
)
from travel_agent.runtime.journal import (
    current_execution_lease,
    current_worker_journal,
)

logger = logging.getLogger(__name__)


ENFORCED_UNAUTHORIZED = "ENFORCED_UNAUTHORIZED"


RESEARCH_WORKER_KINDS = frozenset(RESEARCH_WORKER_NODES)


_WORKER_DOMAINS: Dict[str, frozenset[ResearchDomain]] = {
    "destination_researcher": frozenset(
        {ResearchDomain.VISIT, ResearchDomain.DINING}
    ),
    "accommodation_researcher": frozenset({ResearchDomain.LODGING}),
    "transport_researcher": frozenset(
        {ResearchDomain.LOCAL_TRANSPORT, ResearchDomain.LONG_DISTANCE_TRANSPORT}
    ),
}


_DIGEST_LENGTH = 64


@dataclass(frozen=True)
class OperationAuthorizationDecision:
    """Result of checking one exact tool call against the approved manifest."""

    allowed: bool
    operation_id: Optional[str] = None
    query_id: Optional[str] = None
    reason_code: str = ""


def _denied(reason_code: str) -> OperationAuthorizationDecision:
    return OperationAuthorizationDecision(allowed=False, reason_code=reason_code)


@dataclass(frozen=True)
class ExecutionLeaseObservation:
    """Whether the executing process still owns a live Run lease."""

    live: bool
    reason_code: str
    token: Optional[str] = None


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _valid_digest(value: Any) -> bool:
    text = str(value or "")
    return len(text) == _DIGEST_LENGTH and all(
        character in "0123456789abcdef" for character in text
    )


def _parse_expiry(value: Any) -> Optional[datetime.datetime]:
    if isinstance(value, datetime.datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def _lease_store(config: Optional[Mapping[str, Any]]) -> Any:
    configurable = (config or {}).get("configurable", {})
    if isinstance(configurable, Mapping):
        store = configurable.get("run_execution_store")
        if store is not None:
            return store
    try:
        from travel_agent.bootstrap.registry import get_components

        return getattr(get_components(), "run_execution_store", None)
    except Exception:
        return None


async def observe_execution_lease(
    state: Any,
    config: Optional[Mapping[str, Any]] = None,
) -> ExecutionLeaseObservation:
    """Read the live lease from the run store; absence is not proof of ownership."""

    token = current_execution_lease.get()
    if not token:
        return ExecutionLeaseObservation(False, "lease_token_missing")
    run_id = str(getattr(state, "run_id", "") or "")
    if not run_id:
        return ExecutionLeaseObservation(False, "lease_run_missing", token=str(token))
    store = _lease_store(config)
    if store is None or not hasattr(store, "get"):
        # 没有可核验的执行行时不能把上下文里的 token 当成有效租约。
        return ExecutionLeaseObservation(False, "lease_store_unavailable", str(token))
    try:
        execution = await store.get(run_id)
    except Exception as exc:
        logger.warning("research lease observation failed run_id=%s: %s", run_id, exc)
        return ExecutionLeaseObservation(False, "lease_store_error", str(token))
    if execution is None or str(_field(execution, "lease_token") or "") != str(token):
        return ExecutionLeaseObservation(False, "lease_token_mismatch", str(token))
    expires_at = _parse_expiry(_field(execution, "lease_expires_at"))
    if expires_at is None or expires_at <= datetime.datetime.now(datetime.timezone.utc):
        return ExecutionLeaseObservation(False, "lease_expired", str(token))
    return ExecutionLeaseObservation(True, "", str(token))


@dataclass
class ResearchOperationAuthorization:
    """Approved exact operations available to one research worker invocation."""

    worker_kind: str
    manifest: Optional[ApprovedOperationManifest] = None
    approval: Optional[OperationApproval] = None
    run_id: str = ""
    generation_id: str = ""
    identity_hash: str = ""
    confirmation_hash: str = ""
    query_plan_hash: str = ""
    approval_token: str = ""
    approved_manifest_hash: str = ""
    authorized_query_ids: frozenset[str] = frozenset()
    authorized_evidence_ids: frozenset[str] = frozenset()
    lease: ExecutionLeaseObservation = field(
        default_factory=lambda: ExecutionLeaseObservation(False, "lease_not_observed")
    )
    unauthorized_reason: str = ""
    _operations_by_call: Dict[
        Tuple[str, str], Tuple[AuthorizedToolOperation, ...]
    ] = field(default_factory=dict)
    executed_query_ids: set[str] = field(default_factory=set)
    _journal_seeded: bool = False

    @property
    def authorized(self) -> bool:
        return (
            self.unauthorized_reason == ""
            and self.manifest is not None
            and self.approval is not None
            and self.lease.live
        )

    def _seed_executed_queries_from_journal(self) -> None:
        """Previous authorized attempts in this journal count as executed queries."""

        if self._journal_seeded:
            return
        self._journal_seeded = True
        journal = current_worker_journal.get()
        payload = getattr(journal, "payload", None) if journal else None
        tools = payload.get("tools") if isinstance(payload, Mapping) else None
        if not isinstance(tools, Mapping):
            return
        for entry in tools.values():
            if not isinstance(entry, Mapping) or "result" not in entry:
                continue
            name = entry.get("name")
            arguments = entry.get("arguments")
            if not isinstance(name, str) or not isinstance(arguments, Mapping):
                continue
            try:
                encoded = canonical_operation_arguments(dict(arguments))
            except (TypeError, ValueError):
                continue
            for operation in self._operations_by_call.get((name, encoded), ()):
                if operation.query_id in self.authorized_query_ids:
                    self.executed_query_ids.add(operation.query_id)

    def decision(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> OperationAuthorizationDecision:
        """Allow only an exact approved operation within this assignment's queries."""

        if not self.authorized:
            return _denied(self.unauthorized_reason or "authorization_missing")
        self._seed_executed_queries_from_journal()
        manifest = self.manifest
        approval = self.approval
        if manifest is None or approval is None:
            return _denied("authorization_missing")
        try:
            encoded = canonical_operation_arguments(arguments)
        except (TypeError, ValueError):
            return _denied("operation_arguments_invalid")
        operations = self._operations_by_call.get((tool_name, encoded), ())
        denied_reason = "approved_operation_missing"
        for operation in operations:
            if operation.query_id not in self.authorized_query_ids:
                # 其他 worker 的同一 Provider 调用不能借用本 worker 的分配。
                denied_reason = "operation_not_in_assignment"
                continue
            if operation_is_authorized(
                manifest,
                operation_id=operation.operation_id,
                tool_name=tool_name,
                arguments=arguments,
                run_id=self.run_id,
                generation_id=self.generation_id,
                identity_hash=self.identity_hash,
                confirmation_hash=self.confirmation_hash,
                query_plan_hash=self.query_plan_hash,
                approval_token=self.approval_token,
                approved_manifest_hash=self.approved_manifest_hash,
                live_lease=self.lease.live,
                authorized_query_ids=set(self.authorized_query_ids),
                executed_query_ids=self.executed_query_ids,
                authorized_evidence_ids=set(self.authorized_evidence_ids),
            ):
                self.executed_query_ids.add(operation.query_id)
                return OperationAuthorizationDecision(
                    allowed=True,
                    operation_id=operation.operation_id,
                    query_id=operation.query_id,
                )
        return _denied(denied_reason)


current_operation_authorization: contextvars.ContextVar[
    Optional[ResearchOperationAuthorization]
] = contextvars.ContextVar("research_operation_authorization", default=None)


def current_operation_decision(
    tool_name: str, arguments: Dict[str, Any]
) -> Optional[OperationAuthorizationDecision]:
    """Return ``None`` outside research workers; those calls keep prior behavior."""

    context = current_operation_authorization.get()
    if context is None:
        return None
    return context.decision(tool_name, arguments)


def _parse_manifest(value: Any) -> Optional[ApprovedOperationManifest]:
    if value is None:
        return None
    if isinstance(value, ApprovedOperationManifest):
        return value
    try:
        return ApprovedOperationManifest.model_validate(value)
    except (TypeError, ValueError):
        return None


def _parse_approval(value: Any) -> Optional[OperationApproval]:
    if value is None:
        return None
    if isinstance(value, OperationApproval):
        return value
    try:
        return OperationApproval.model_validate(value)
    except (TypeError, ValueError):
        return None


def research_authorization_scope(
    state: Any, *, approval_token: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    """Return the exact run scope bound by the final plan approval, or ``None``."""

    generation = getattr(state, "planning_generation", None)
    plan = getattr(state, "research_query_plan", None)
    contract = getattr(state, "request_contract", None)
    approval = getattr(state, "research_operation_approval", None)
    token = str(
        approval_token
        or _field(approval, "approval_token", "")
        or getattr(state, "plan_gate_approval_token", "")
        or ""
    ).strip()
    run_id = str(getattr(state, "run_id", "") or "")
    identity_hash = canonical_json_hash(getattr(state, "controlled_trip_identity", {}) or {})
    contract_hash = str(_field(contract, "content_hash", "") or "")
    query_plan_hash = str(_field(plan, "content_hash", "") or "")
    generation_id = str(_field(generation, "generation_id", "") or "")
    if (
        not run_id
        or not generation_id
        or not token
        or not _valid_digest(contract_hash)
        or not _valid_digest(query_plan_hash)
        or str(_field(plan, "generation_id", "") or "") != generation_id
    ):
        return None
    confirmation_hash = research_approval_confirmation_hash(contract_hash, token)
    return {
        "run_id": run_id,
        "generation_id": generation_id,
        "identity_hash": identity_hash,
        "confirmation_hash": confirmation_hash,
        "query_plan_hash": query_plan_hash,
    }


def _scope_hashes(
    state: Any,
) -> Optional[tuple[str, str, str, str]]:
    """Return (identity, confirmation, query plan, generation) or None."""

    scope = research_authorization_scope(state)
    if scope is None:
        return None
    return (
        scope["identity_hash"],
        scope["confirmation_hash"],
        scope["query_plan_hash"],
        scope["generation_id"],
    )


def _assignment_queries(state: Any, worker_kind: str) -> Optional[frozenset[str]]:
    plan = getattr(state, "research_query_plan", None)
    generation = getattr(state, "planning_generation", None)
    assignments = getattr(state, "agent_assignments", None) or {}
    try:
        _key, assignment = resolve_agent_assignment(assignments, worker_kind)
    except (TypeError, ValueError):
        return None
    if str(assignment.get("generation_id") or "") != str(
        _field(generation, "generation_id", "") or ""
    ):
        return None
    query_ids = assignment.get("research_query_ids")
    if not isinstance(query_ids, list) or not query_ids:
        return None
    index = getattr(plan, "query_index", lambda: {})()
    if not set(query_ids) <= set(index):
        return None
    domains = _WORKER_DOMAINS.get(worker_kind, frozenset())
    if any(index[str(query_id)].domain not in domains for query_id in query_ids):
        return None
    return frozenset(str(item) for item in query_ids)


def build_research_worker_authorization(
    state: Any,
    *,
    worker_kind: str,
    lease: ExecutionLeaseObservation,
) -> ResearchOperationAuthorization:
    """Bind the manifest, approval record, assignment and live lease together."""

    context = ResearchOperationAuthorization(worker_kind=worker_kind, lease=lease)
    if worker_kind not in RESEARCH_WORKER_KINDS:
        context.unauthorized_reason = "unsupported_research_worker"
        return context

    context.run_id = str(getattr(state, "run_id", "") or "")
    raw_manifest = getattr(state, "research_operation_manifest", None)
    raw_approval = getattr(state, "research_operation_approval", None)
    if raw_manifest is None:
        context.unauthorized_reason = "missing_operation_manifest"
        return context
    if raw_approval is None:
        context.unauthorized_reason = "missing_operation_approval"
        return context

    manifest = _parse_manifest(raw_manifest)
    if manifest is None:
        context.unauthorized_reason = "operation_manifest_invalid"
        return context
    approval = _parse_approval(raw_approval)
    if approval is None:
        context.unauthorized_reason = "operation_approval_invalid"
        return context

    hashes = _scope_hashes(state)
    if hashes is None:
        context.unauthorized_reason = "authorization_scope_missing"
        return context
    identity_hash, confirmation_hash, query_plan_hash, generation_id = hashes
    context.identity_hash = identity_hash
    context.confirmation_hash = confirmation_hash
    context.query_plan_hash = query_plan_hash
    context.generation_id = generation_id
    context.manifest = manifest
    context.approval = approval
    context.approval_token = approval.approval_token
    # 只信任独立批准记录里的 hash；manifest 只能被它约束，不能自我证明。
    context.approved_manifest_hash = approval.approved_manifest_hash

    expected = {
        "run_id": context.run_id,
        "generation_id": generation_id,
        "identity_hash": identity_hash,
        "confirmation_hash": confirmation_hash,
        "query_plan_hash": query_plan_hash,
    }
    if any(
        str(_field(manifest, key, "") or "") != value
        or str(_field(approval, key, "") or "") != value
        for key, value in expected.items()
    ):
        context.unauthorized_reason = "approval_scope_mismatch"
        return context
    if manifest.approval_token != approval.approval_token:
        context.unauthorized_reason = "approval_token_mismatch"
        return context
    if approval.approved_manifest_hash != manifest.manifest_hash:
        context.unauthorized_reason = "approved_manifest_hash_mismatch"
        return context

    authorized_query_ids = _assignment_queries(state, worker_kind)
    if authorized_query_ids is None:
        context.unauthorized_reason = "assignment_scope_missing"
        return context
    context.authorized_query_ids = authorized_query_ids

    operations_by_call: Dict[
        Tuple[str, str], list[AuthorizedToolOperation]
    ] = {}
    for operation in manifest.operations:
        try:
            encoded = canonical_operation_arguments(json.loads(operation.arguments_json))
        except (TypeError, ValueError):
            context.unauthorized_reason = "operation_manifest_invalid"
            return context
        operations_by_call.setdefault(
            (operation.tool_name, encoded), []
        ).append(operation)
    context._operations_by_call = {
        key: tuple(items) for key, items in operations_by_call.items()
    }

    if not lease.live:
        context.unauthorized_reason = lease.reason_code or "lease_invalid"
        return context
    return context


def research_authorization_binding(state: Any, node_name: str) -> Optional[Dict[str, Any]]:
    """Journal scope material so a different approval cannot replay old results."""

    if node_name not in RESEARCH_WORKER_KINDS:
        return None
    approval = getattr(state, "research_operation_approval", None)
    manifest = getattr(state, "research_operation_manifest", None)
    if approval is None and manifest is None:
        return None
    approval_data = (
        approval.model_dump(mode="json")
        if hasattr(approval, "model_dump")
        else approval
    )
    manifest_hash = (
        str(_field(manifest, "manifest_hash", "") or "")
        if manifest is not None
        else ""
    )
    return {"approval": approval_data, "manifest_hash": manifest_hash}
