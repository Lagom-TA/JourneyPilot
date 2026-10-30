"""Exact research Provider authorization without sockets or a database."""

from __future__ import annotations

import datetime
import json
from types import SimpleNamespace
from typing import Any, Dict

import pytest

from travel_agent.planning.requirements.intent_contracts import canonical_json_hash
from travel_agent.planning.research import operation_authority
from travel_agent.planning.research.authorization_context import (
    ENFORCED_UNAUTHORIZED,
    ExecutionLeaseObservation,
    build_research_worker_authorization,
    current_operation_authorization,
)
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.operation_authority import (
    ApprovedOperationManifest,
    build_authorized_operation,
    build_operation_approval,
    canonical_operation_arguments,
    research_approval_confirmation_hash,
)
from travel_agent.planning.research.operation_compiler import (
    compile_and_approve_research_operations,
)
from travel_agent.planning.research.provider_assignments import (
    build_provider_evidence_assignments,
    dump_provider_evidence_assignments,
)
from travel_agent.planning.research.provider_contracts import ProviderRouteLegScope
from travel_agent.planning.research.query_contracts import (
    ResearchQuery,
    ResearchQueryPlan,
)
from travel_agent.planning.recovery import with_worker_recovery
from travel_agent.runtime.context import current_node
from travel_agent.runtime.journal import (
    WorkerJournal,
    current_execution_lease,
    current_worker_journal,
)
from travel_agent.storage.worker_journal_store import InMemoryWorkerJournalStore
from travel_agent.tools import execution as execution_module
from travel_agent.tools import react
from travel_agent.tools.gateway_contracts import (
    ToolGatewayDecision,
    ToolGatewayPolicyResult,
    ToolManifest,
)


RUN_ID = "run-authorization"
GENERATION_ID = "generation-authorization"
RECEIPT_HASH = "d" * 64
APPROVAL_TOKEN = "plan_gate.approval.v1:offline"


def _place(name: str) -> Dict[str, Any]:
    return {
        "place_id": f"offline:{name}",
        "provider": "osm",
        "kind": "city",
        "name": name,
        "display_name": name,
        "country_code": "CN",
        "latitude": 31.2,
        "longitude": 121.4,
        "admin_path": [],
    }


IDENTITY = {
    "origin": _place("上海"),
    "destinations": [_place("杭州")],
    "start_date": "2026-11-05",
    "end_date": "2026-11-07",
    "party": {"adults": 2, "children": 0},
    "style": {"primary": "经典均衡", "secondary_interests": []},
}


def _query(
    query_id: str,
    domain: ResearchDomain,
    text: str,
    *,
    kind: str = "structural",
    aliases: list[str] | None = None,
    after: list[str] | None = None,
    route: str = "web_discovery",
) -> ResearchQuery:
    return ResearchQuery.model_validate(
        {
            "query_id": query_id,
            "generation_id": GENERATION_ID,
            "domain": domain.value,
            "destination_id": "offline:杭州",
            "query_kind": kind,
            "query_text": text,
            "aliases": aliases or [],
            "desired_candidate_count": 2,
            "provider_route": route,
            "priority": 60,
            "fallback_after_query_ids": after or [],
        }
    )


QUERIES = [
    _query("q_visit", ResearchDomain.VISIT, "杭州 景点", aliases=["景点"]),
    _query(
        "q_visit_place",
        ResearchDomain.VISIT,
        "杭州 地标",
        route="global_place_search",
    ),
    _query("q_dining", ResearchDomain.DINING, "杭州 素食", aliases=["素食"]),
    _query(
        "q_dining_fallback",
        ResearchDomain.DINING,
        "restaurant in 杭州",
        kind="generic_fallback",
        after=["q_dining"],
    ),
    _query(
        "q_lodging", ResearchDomain.LODGING, "杭州 酒店", aliases=["酒店"], route="mixed"
    ),
    _query(
        "q_rail",
        ResearchDomain.LONG_DISTANCE_TRANSPORT,
        "上海 杭州 高铁",
        route="rail_provider",
    ),
    _query(
        "q_local",
        ResearchDomain.LOCAL_TRANSPORT,
        "杭州 公交",
        route="route_provider",
    ),
]

QUERY_PLAN = ResearchQueryPlan(
    query_plan_id="query_plan_offline",
    generation_id=GENERATION_ID,
    intent_spec_revision=1,
    queries=QUERIES,
    per_domain_candidate_caps={domain.value: 5 for domain in ResearchDomain},
    policy_version="research_query_planner.v3",
    content_hash=canonical_json_hash(
        {"generation": GENERATION_ID, "queries": [item.query_id for item in QUERIES]}
    ),
)

ROUTE_LEG = ProviderRouteLegScope(
    leg_role="outbound",
    from_place_id="offline:上海",
    to_place_id="offline:杭州",
    service_date=datetime.date(2026, 11, 5),
)


def _assignment(
    worker_kind: str,
    query_ids: list[str],
    *,
    candidate_kinds: list[str] | None = None,
    transport_classes: list[str] | None = None,
) -> Dict[str, Any]:
    provider_assignments = build_provider_evidence_assignments(
        run_id=RUN_ID,
        constraint_pack_revision=0,
        worker_kind=worker_kind,
        controlled_trip_identity=IDENTITY,
        prior_scope_attempts={},
        candidate_kinds=candidate_kinds,
        transport_classes=transport_classes,
        long_distance_legs=[ROUTE_LEG] if transport_classes else None,
    )
    return {
        "assignment_id": f"assignment_{worker_kind}",
        "generation_id": GENERATION_ID,
        "agent_name": worker_kind,
        "objective": f"{worker_kind} offline objective",
        "research_query_ids": list(query_ids),
        "research_objective_ids": [],
        "must_cover_intent_ids": [],
        "optional_intent_ids": [],
        "required_candidate_kinds": candidate_kinds or [],
        "excluded_categories": [],
        "success_criteria": [],
        "recommended_tools": [],
        "upstream_assignment_ids": [],
        "intent_spec_revision": 1,
        "constraint_pack_revision": 0,
        "provider_evidence_assignments": dump_provider_evidence_assignments(
            provider_assignments
        ),
    }


ASSIGNMENTS = {
    "destination_researcher": _assignment(
        "destination_researcher",
        ["q_visit", "q_visit_place", "q_dining", "q_dining_fallback"],
        candidate_kinds=["visit", "dining"],
    ),
    "accommodation_researcher": _assignment(
        "accommodation_researcher", ["q_lodging"]
    ),
    "transport_researcher": _assignment(
        "transport_researcher",
        ["q_rail"],
        transport_classes=["long_distance"],
    ),
}


def _state(
    *,
    manifest: Any = None,
    approval: Any = None,
    assignments: Dict[str, Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        run_id=RUN_ID,
        controlled_trip_identity=IDENTITY,
        controlled_trip_identity_revision=1,
        constraint_pack_revision=0,
        planning_generation=SimpleNamespace(generation_id=GENERATION_ID),
        request_contract=SimpleNamespace(content_hash="c" * 64),
        semantic_receipt=SimpleNamespace(
            receipt_hash=RECEIPT_HASH,
            run_id=RUN_ID,
            identity_hash=canonical_json_hash(IDENTITY),
            incomplete=False,
        ),
        research_query_plan=QUERY_PLAN,
        agent_assignments=assignments if assignments is not None else ASSIGNMENTS,
        research_operation_manifest=manifest,
        research_operation_approval=approval,
    )


@pytest.fixture(scope="module")
def compiled():
    manifest, approval, limitations = compile_and_approve_research_operations(
        _state(), approval_token=APPROVAL_TOKEN
    )
    assert manifest is not None and approval is not None
    return manifest, approval, limitations


def _context(
    manifest: Any,
    approval: Any,
    *,
    worker_kind: str = "destination_researcher",
    lease: ExecutionLeaseObservation | None = None,
):
    return build_research_worker_authorization(
        _state(manifest=manifest, approval=approval),
        worker_kind=worker_kind,
        lease=lease or ExecutionLeaseObservation(True, "", "lease-token"),
    )


def _operations(manifest: ApprovedOperationManifest, tool: str, arguments: Dict):
    encoded = canonical_operation_arguments(arguments)
    return [
        operation
        for operation in manifest.operations
        if operation.tool_name == tool and operation.arguments_json == encoded
    ]


def test_compiler_covers_exact_primary_fallback_and_rail_operations(compiled):
    manifest, approval, limitations = compiled
    assert approval.approved_manifest_hash == manifest.manifest_hash
    assert approval.approval_token == APPROVAL_TOKEN
    assert _operations(
        manifest, "maps_text_search", {"keywords": "景点", "city": "杭州"}
    )
    assert _operations(
        manifest,
        "global_place_search",
        {
            "query": "杭州 地标",
            "country_code": "cn",
            "limit": 10,
            "candidate_kind": "visit",
            "aliases": [],
            "destination_place_id": "offline:杭州",
            "destination_latitude": 31.2,
            "destination_longitude": 121.4,
        },
    )
    assert _operations(
        manifest, "maps_text_search", {"keywords": "素食", "city": "杭州"}
    )
    assert _operations(
        manifest, "maps_text_search", {"keywords": "杭州 酒店", "city": "杭州"}
    )
    assert _operations(
        manifest, "get-station-code-of-citys", {"citys": "上海|杭州"}
    )
    assert _operations(
        manifest,
        "get-tickets",
        {"date": "2026-11-05", "fromStation": "AOH", "toStation": "HGH"},
    )
    assert any("maps_search_detail" in item for item in limitations)


def test_approved_operation_is_allowed_but_parameter_changes_are_not(compiled):
    manifest, approval, _limitations = compiled
    context = _context(manifest, approval)
    assert context.authorized

    allowed = context.decision(
        "maps_text_search", {"keywords": "景点", "city": "杭州"}
    )
    assert allowed.allowed and allowed.query_id == "q_visit"
    for arguments in (
        {"keywords": "景点", "city": "苏州"},
        {"keywords": "牛肉", "city": "杭州"},
        {"keywords": "景点", "city": "杭州", "extra": True},
    ):
        assert context.decision("maps_text_search", arguments).allowed is False
    assert context.decision("free_web_search", {"query": "未批准查询"}).allowed is False


def test_tampered_manifest_is_not_self_approved(compiled):
    manifest, approval, _limitations = compiled
    poisoned = build_authorized_operation(
        tool_name="maps_text_search",
        query_id="q_visit",
        arguments={"keywords": "付费景点", "city": "杭州"},
    )
    payload = manifest.model_dump(mode="json")
    payload["manifest_hash"] = ""
    payload["operations"] = [poisoned.model_dump(mode="json")]
    tampered = ApprovedOperationManifest.model_validate(payload)
    context = _context(tampered, approval)
    assert not context.authorized
    assert context.unauthorized_reason == "approved_manifest_hash_mismatch"
    assert context.decision(
        "maps_text_search", {"keywords": "付费景点", "city": "杭州"}
    ).allowed is False


def test_tampered_approval_hash_blocks_every_call(compiled):
    manifest, approval, _limitations = compiled
    tampered_approval = approval.model_copy(
        update={"approved_manifest_hash": "0" * 64}
    )
    context = _context(manifest, tampered_approval)
    assert not context.authorized
    assert context.unauthorized_reason == "approved_manifest_hash_mismatch"


def test_generic_fallback_waits_for_its_primary_query(compiled):
    manifest, approval, _limitations = compiled
    context = _context(manifest, approval)
    fallback_arguments = {"query": "restaurant in 杭州", "max_results": 5}
    assert context.decision("free_web_search", fallback_arguments).allowed is False
    assert context.decision(
        "maps_text_search", {"keywords": "素食", "city": "杭州"}
    ).allowed
    assert context.decision("free_web_search", fallback_arguments).allowed


def test_worker_cannot_spend_another_workers_query(compiled):
    manifest, approval, _limitations = compiled
    transport = _context(
        manifest, approval, worker_kind="transport_researcher"
    )
    decision = transport.decision(
        "maps_text_search", {"keywords": "景点", "city": "杭州"}
    )
    assert not decision.allowed
    assert decision.reason_code == "operation_not_in_assignment"


def test_assignment_cannot_import_another_workers_query_ids(compiled):
    manifest, approval, _limitations = compiled
    poisoned = {
        **ASSIGNMENTS,
        "transport_researcher": {
            **ASSIGNMENTS["transport_researcher"],
            "research_query_ids": ["q_visit"],
        },
    }
    context = build_research_worker_authorization(
        _state(manifest=manifest, approval=approval, assignments=poisoned),
        worker_kind="transport_researcher",
        lease=ExecutionLeaseObservation(True, "", "lease-token"),
    )
    assert not context.authorized
    assert context.unauthorized_reason == "assignment_scope_missing"


def test_missing_or_stale_lease_is_enforced_unauthorized(compiled):
    manifest, approval, _limitations = compiled
    for lease in (
        ExecutionLeaseObservation(False, "lease_token_missing"),
        ExecutionLeaseObservation(False, "lease_expired"),
        ExecutionLeaseObservation(False, "lease_token_mismatch"),
    ):
        context = _context(manifest, approval, lease=lease)
        assert not context.authorized
        assert context.decision(
            "maps_text_search", {"keywords": "景点", "city": "杭州"}
        ).allowed is False


def test_unknown_worker_or_missing_record_is_enforced_unauthorized(compiled):
    manifest, approval, _limitations = compiled
    assert not _context(manifest, approval, worker_kind="itinerary_planner").authorized
    missing = build_research_worker_authorization(
        _state(manifest=None, approval=None),
        worker_kind="destination_researcher",
        lease=ExecutionLeaseObservation(True, "", "lease-token"),
    )
    assert not missing.authorized
    assert missing.unauthorized_reason == "missing_operation_manifest"


async def test_execute_tool_blocks_before_registry_when_operation_is_unapproved(
    compiled, monkeypatch
):
    manifest, approval, _limitations = compiled
    context = _context(manifest, approval)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("provider registry must not be reached")

    monkeypatch.setattr(execution_module, "get_tool_registry", forbidden)
    token = current_operation_authorization.set(context)
    try:
        result = await execution_module.execute_tool(
            "maps_text_search", {"keywords": "牛肉", "city": "杭州"}
        )
    finally:
        current_operation_authorization.reset(token)
    assert result["status"] == "blocked"
    assert result["error"] == ENFORCED_UNAUTHORIZED
    assert result["sanitized_result"] is None
    assert result["metadata"]["authorization_reason"] == "approved_operation_missing"


async def test_execute_tool_without_research_context_keeps_prior_behavior(monkeypatch):
    calls = []

    async def once(*_args, **_kwargs):
        calls.append(1)
        return {"status": "success", "sanitized_result": {"ok": True}}

    monkeypatch.setattr(execution_module, "_execute_tool_once", once)
    result = await execution_module.execute_tool(
        "maps_text_search", {"keywords": "景点", "city": "杭州"}
    )
    assert result == {"status": "success", "sanitized_result": {"ok": True}}
    assert calls == [1]


async def test_authorized_journal_replay_is_kept_but_unauthorized_replay_is_blocked(
    compiled, monkeypatch
):
    manifest, approval, _limitations = compiled
    context = _context(manifest, approval)
    store = InMemoryWorkerJournalStore()
    calls = []

    async def once(*_args, **_kwargs):
        calls.append(1)
        return {"status": "success", "sanitized_result": {"value": 1}}

    monkeypatch.setattr(
        execution_module,
        "get_tool_registry",
        lambda: SimpleNamespace(get_tool_metadata=lambda _name: {}),
    )
    monkeypatch.setattr(execution_module, "_execute_tool_once", once)
    journal = WorkerJournal(store, RUN_ID, "scope", 0, {}, "lease-token")
    token = current_worker_journal.set(journal)
    auth_token = current_operation_authorization.set(context)
    try:
        first = await execution_module.execute_tool(
            "maps_text_search", {"keywords": "景点", "city": "杭州"}
        )
    finally:
        current_operation_authorization.reset(auth_token)
        current_worker_journal.reset(token)
    assert first["status"] == "success" and calls == [1]

    version, payload = await store.load(RUN_ID, "scope")
    restored = WorkerJournal(store, RUN_ID, "scope", version, payload, "lease-token")
    token = current_worker_journal.set(restored)
    auth_token = current_operation_authorization.set(context)
    try:
        replayed = await execution_module.execute_tool(
            "maps_text_search", {"keywords": "景点", "city": "杭州"}
        )
    finally:
        current_operation_authorization.reset(auth_token)
        current_worker_journal.reset(token)
    assert replayed == first and calls == [1]

    denied = _context(
        manifest, approval, lease=ExecutionLeaseObservation(False, "lease_expired")
    )
    restored = WorkerJournal(store, RUN_ID, "scope", version, payload, "lease-token")
    token = current_worker_journal.set(restored)
    auth_token = current_operation_authorization.set(denied)
    try:
        blocked = await execution_module.execute_tool(
            "maps_text_search", {"keywords": "景点", "city": "杭州"}
        )
    finally:
        current_operation_authorization.reset(auth_token)
        current_worker_journal.reset(token)
    assert blocked["status"] == "blocked"
    assert blocked["error"] == ENFORCED_UNAUTHORIZED
    assert calls == [1]


class _Gateway:
    async def before_call(self, *, tool_name, **_kwargs):
        return ToolGatewayPolicyResult(
            decision=ToolGatewayDecision.ALLOW,
            manifest=ToolManifest(tool_name=tool_name),
            envelope=None,
        )

    async def after_call(self, envelope, **_kwargs):
        return envelope


class _SnapshotRecord:
    def trace_metadata(self, **_kwargs):
        return {}


class _SnapshotCache:
    def __init__(self):
        self.lookups = 0

    async def lookup(self, _scope):
        self.lookups += 1
        return SimpleNamespace(
            outcome="hit",
            record=SimpleNamespace(
                snapshot={"results": [], "retrieved_at": "2026-11-01T00:00:00+00:00"},
                trace_metadata=self._metadata(),
            ),
        )

    def _metadata(self):
        return _SnapshotRecord().trace_metadata


async def test_authorization_runs_before_provider_snapshot_cache(compiled, monkeypatch):
    manifest, approval, _limitations = compiled
    context = _context(manifest, approval)
    cache = _SnapshotCache()

    class Registry:
        def get_tool_metadata(self, _name):
            return {}

        async def execute(self, *_args, **_kwargs):
            raise AssertionError("provider must not be called on a cache hit")

    monkeypatch.setattr(execution_module, "get_tool_registry", lambda: Registry())
    monkeypatch.setattr(execution_module, "get_tool_gateway", lambda: _Gateway())
    token = current_operation_authorization.set(context)
    try:
        result = await execution_module.execute_tool(
            "maps_text_search",
            {"keywords": "景点", "city": "杭州"},
            provider_snapshot_cache=cache,
        )
    finally:
        current_operation_authorization.reset(token)
    assert result["status"] == "success"
    assert cache.lookups == 1

    denied = _context(
        manifest, approval, lease=ExecutionLeaseObservation(False, "lease_expired")
    )
    token = current_operation_authorization.set(denied)
    try:
        blocked = await execution_module.execute_tool(
            "maps_text_search",
            {"keywords": "景点", "city": "杭州"},
            provider_snapshot_cache=cache,
        )
    finally:
        current_operation_authorization.reset(token)
    assert blocked["status"] == "blocked"
    assert cache.lookups == 1


class _FallbackRegistry:
    def __init__(self):
        self.executed = []

    def get_tool_metadata(self, _name):
        return {}

    def has_tool(self, _name):
        return True

    async def execute(self, name, **arguments):
        self.executed.append((name, arguments))
        if name == "tavily_search":
            return {"success": False, "error": "offline failure"}
        return {
            "success": True,
            "results": [{"title": "fallback result"}],
            "retrieved_at": "2026-11-01T00:00:00+00:00",
        }


async def test_fallback_provider_call_needs_its_own_approved_operation(
    compiled, monkeypatch
):
    manifest, approval, _limitations = compiled
    context = _context(manifest, approval)
    registry = _FallbackRegistry()
    monkeypatch.setattr(execution_module, "get_tool_registry", lambda: registry)
    monkeypatch.setattr(execution_module, "get_tool_gateway", lambda: _Gateway())
    token = current_operation_authorization.set(context)
    try:
        result = await execution_module.execute_tool(
            "tavily_search", {"query": "杭州 景点", "max_results": 5}
        )
    finally:
        current_operation_authorization.reset(token)
    assert [item[0] for item in registry.executed] == [
        "tavily_search",
        "free_web_search",
    ]
    assert registry.executed[1][1] == {"query": "杭州 景点 旅游攻略 景点"}
    assert result["status"] == "degraded"
    assert result["fallback_to"] == "free_web_search"

    fallback_only = build_authorized_operation(
        tool_name="tavily_search",
        query_id="q_visit",
        arguments={"query": "杭州 景点", "max_results": 5},
    )
    fallback_manifest = ApprovedOperationManifest(
        run_id=RUN_ID,
        generation_id=GENERATION_ID,
        identity_hash=canonical_json_hash(IDENTITY),
        confirmation_hash=research_approval_confirmation_hash("c" * 64, APPROVAL_TOKEN),
        query_plan_hash=QUERY_PLAN.content_hash,
        approval_token=APPROVAL_TOKEN,
        operations=(fallback_only,),
    )
    fallback_approval = build_operation_approval(manifest=fallback_manifest)
    denied_context = _context(fallback_manifest, fallback_approval)
    registry = _FallbackRegistry()
    monkeypatch.setattr(execution_module, "get_tool_registry", lambda: registry)
    token = current_operation_authorization.set(denied_context)
    try:
        blocked = await execution_module.execute_tool(
            "tavily_search", {"query": "杭州 景点", "max_results": 5}
        )
    finally:
        current_operation_authorization.reset(token)
    assert [item[0] for item in registry.executed] == ["tavily_search"]
    assert blocked["status"] == "blocked"
    assert blocked["error"] == ENFORCED_UNAUTHORIZED


async def test_authorized_fallback_journal_is_replayed_without_a_provider_call(
    compiled, monkeypatch
):
    manifest, approval, _limitations = compiled
    store = InMemoryWorkerJournalStore()
    registry = _FallbackRegistry()
    monkeypatch.setattr(execution_module, "get_tool_registry", lambda: registry)
    monkeypatch.setattr(execution_module, "get_tool_gateway", lambda: _Gateway())

    def fresh_journal():
        return WorkerJournal(store, RUN_ID, "scope", 0, {}, "lease-token")

    token = current_worker_journal.set(fresh_journal())
    auth_token = current_operation_authorization.set(_context(manifest, approval))
    try:
        await execution_module.execute_tool(
            "tavily_search", {"query": "杭州 景点", "max_results": 5}
        )
    finally:
        current_operation_authorization.reset(auth_token)
        current_worker_journal.reset(token)
    assert [item[0] for item in registry.executed] == [
        "tavily_search",
        "free_web_search",
    ]

    version, payload = await store.load(RUN_ID, "scope")
    registry.executed.clear()

    def replay_journal():
        return WorkerJournal(store, RUN_ID, "scope", version, payload, "lease-token")

    token = current_worker_journal.set(replay_journal())
    auth_token = current_operation_authorization.set(_context(manifest, approval))
    try:
        replayed_primary = await execution_module.execute_tool(
            "tavily_search", {"query": "杭州 景点", "max_results": 5}
        )
    finally:
        current_operation_authorization.reset(auth_token)
        current_worker_journal.reset(token)
    assert replayed_primary["status"] == "degraded"
    assert replayed_primary["fallback_to"] == "free_web_search"
    assert registry.executed == []


async def test_destination_discovery_calls_match_the_compiled_operations(
    compiled, monkeypatch
):
    from travel_agent.planning.research.destination import discovery

    manifest, approval, _limitations = compiled
    context = _context(manifest, approval)
    calls = []

    async def once(name, arguments, *_args, **_kwargs):
        calls.append((name, dict(arguments)))
        return {
            "tool_name": name,
            "status": "success",
            "audit_id": f"audit_{len(calls)}",
            "retrieved_at": "2026-11-01T00:00:00+00:00",
            "sanitized_result": {"results": []},
            "metadata": {"provider_result_outcome": "empty_success"},
        }

    monkeypatch.setattr(execution_module, "_execute_tool_once", once)
    monkeypatch.setattr(discovery, "runtime_fallback_capacity", lambda: (True, True))
    messages, results, executed = [], [], []
    token = current_operation_authorization.set(context)
    try:
        await discovery.discover_and_resolve_required_places(
            messages=messages,
            available_tools=[
                {
                    "schema": {
                        "function": {
                            "name": name,
                            "parameters": {"type": "object"},
                        }
                    }
                }
                for name in (
                    "free_web_search",
                    "maps_text_search",
                    "global_place_search",
                )
            ],
            required_candidate_kinds=["visit", "dining"],
            destination_boundaries=[
                {
                    "destination_id": "offline:杭州",
                    "name": "杭州",
                    "country_code": "cn",
                    "latitude": 31.2,
                    "longitude": 121.4,
                }
            ],
            tool_context={},
            authoritative_tool_results=results,
            planned_queries=QUERIES,
            executed_query_ids=executed,
        )
    finally:
        current_operation_authorization.reset(token)

    assert ("free_web_search", {"query": "杭州 景点", "max_results": 5}) in calls
    assert (
        "global_place_search",
        {
            "query": "杭州 地标",
            "country_code": "cn",
            "limit": 10,
            "candidate_kind": "visit",
            "aliases": [],
            "destination_place_id": "offline:杭州",
            "destination_latitude": 31.2,
            "destination_longitude": 121.4,
        },
    ) in calls
    assert ("maps_text_search", {"keywords": "素食", "city": "杭州"}) in calls
    assert (
        "free_web_search",
        {"query": "restaurant in 杭州", "max_results": 5},
    ) in calls
    assert set(executed) >= {"q_visit", "q_visit_place", "q_dining"}


async def test_react_tool_call_must_match_an_approved_operation(
    compiled, monkeypatch
):
    manifest, approval, _limitations = compiled
    context = _context(manifest, approval)

    class Model:
        def __init__(self):
            self.calls = 0

        async def astream_with_tools(self, messages, _schemas):
            self.calls += 1
            if self.calls == 1:
                yield {
                    "type": "finish",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "tc1",
                            "name": "maps_text_search",
                            "arguments": {"keywords": "牛肉", "city": "苏州"},
                        }
                    ],
                }
            else:
                yield {"type": "finish", "content": "最终回答", "tool_calls": []}

    tools = [
        {
            "schema": {
                "type": "function",
                "function": {
                    "name": "maps_text_search",
                    "parameters": {"type": "object"},
                },
            }
        }
    ]
    monkeypatch.setattr(react, "execute_tool", execution_module.execute_tool)
    monkeypatch.setattr(react, "remaining_model_seconds", lambda *_a, **_k: None)
    token = current_operation_authorization.set(context)
    try:
        result = await react.streaming_react_loop(
            Model(), [], tools, None, "destination_researcher", max_iterations=2
        )
    finally:
        current_operation_authorization.reset(token)
    assert result.require_final_answer() == "最终回答"
    assert result.tool_results[0]["status"] == "blocked"
    assert result.tool_results[0]["error"] == ENFORCED_UNAUTHORIZED


class _LeaseStore:
    def __init__(self, token, expires_at):
        self.token = token
        self.expires_at = expires_at

    async def get(self, _run_id):
        return SimpleNamespace(
            lease_token=self.token, lease_expires_at=self.expires_at
        )


def _future() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(minutes=5)
    ).isoformat()


async def _call_worker_through_wrapper(
    state, monkeypatch, *, lease_store, worker=None
):
    calls = []

    async def default_worker(_state, _config):
        return await execution_module.execute_tool(
            "maps_text_search", {"keywords": "景点", "city": "杭州"}
        )

    worker = worker or default_worker

    async def once(*_args, **_kwargs):
        calls.append(1)
        return {"status": "success", "sanitized_result": {"ok": True}}

    monkeypatch.setattr(execution_module, "_execute_tool_once", once)
    lease_token = current_execution_lease.set("lease-token")
    try:
        result = await with_worker_recovery("destination_researcher", worker)(
            state, {"configurable": {"run_execution_store": lease_store}}
        )
    finally:
        current_execution_lease.reset(lease_token)
    return result, calls


async def test_wrapper_blocks_deep_research_without_approval(monkeypatch):
    with pytest.raises(PermissionError, match="not authorized"):
        await _call_worker_through_wrapper(
            _state(manifest=None, approval=None),
            monkeypatch,
            lease_store=_LeaseStore("lease-token", _future()),
        )


async def test_wrapper_requires_the_live_lease_token(monkeypatch):
    manifest, approval, _limitations = compile_and_approve_research_operations(
        _state(), approval_token=APPROVAL_TOKEN
    )
    state = _state(manifest=manifest, approval=approval)
    with pytest.raises(PermissionError, match="not authorized"):
        await _call_worker_through_wrapper(
            state, monkeypatch, lease_store=_LeaseStore("other-token", _future())
        )

    expired = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(minutes=1)
    ).isoformat()
    with pytest.raises(PermissionError, match="not authorized"):
        await _call_worker_through_wrapper(
            state, monkeypatch, lease_store=_LeaseStore("lease-token", expired)
        )


async def test_wrapper_allows_an_exactly_approved_call(monkeypatch):
    manifest, approval, _limitations = compile_and_approve_research_operations(
        _state(), approval_token=APPROVAL_TOKEN
    )
    state = _state(manifest=manifest, approval=approval)
    result, calls = await _call_worker_through_wrapper(
        state, monkeypatch, lease_store=_LeaseStore("lease-token", _future())
    )
    assert result["status"] == "success"
    assert calls == [1]


class _JournalState(SimpleNamespace):
    def model_dump(self, **_kwargs):
        return {}


async def test_unauthorized_worker_does_not_replay_a_cached_result(monkeypatch):
    from travel_agent.planning.recovery import invocation_scope

    store = InMemoryWorkerJournalStore()
    state = _JournalState(**_state(manifest=None, approval=None).__dict__)
    config = {"configurable": {"worker_journal_store": store}}
    scope = invocation_scope(state, "destination_researcher", config)
    await store.save(
        RUN_ID,
        scope,
        0,
        {"worker_result": {"status": "stale-cached-result"}},
    )
    calls = []

    async def worker(_state, _config):
        calls.append(1)
        return {"status": "fresh-result"}

    lease_token = current_execution_lease.set("lease-token")
    try:
        with pytest.raises(PermissionError, match="not authorized"):
            await with_worker_recovery("destination_researcher", worker)(
                state,
                {
                    "configurable": {
                        "worker_journal_store": store,
                        "run_execution_store": _LeaseStore("lease-token", _future()),
                    }
                },
            )
    finally:
        current_execution_lease.reset(lease_token)
    assert calls == []


async def test_research_node_without_context_cannot_call_a_provider(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("provider registry must not be reached")

    monkeypatch.setattr(execution_module, "get_tool_registry", forbidden)
    token = current_node.set("destination_researcher")
    try:
        result = await execution_module.execute_tool(
            "maps_text_search", {"keywords": "景点", "city": "杭州"}
        )
    finally:
        current_node.reset(token)
    assert result["status"] == "blocked"
    assert result["error"] == ENFORCED_UNAUTHORIZED
    assert result["metadata"]["authorization_reason"] == (
        "missing_research_authorization"
    )


def test_approval_hash_is_only_read_from_the_independent_record(compiled):
    manifest, approval, _limitations = compiled
    assert approval.approved_manifest_hash == manifest.manifest_hash
    operation = _operations(
        manifest, "maps_text_search", {"keywords": "景点", "city": "杭州"}
    )[0]
    # The primitive receives the record hash; a manifest cannot supply its own.
    assert operation_authority.operation_is_authorized(
        manifest,
        operation_id=operation.operation_id,
        tool_name=operation.tool_name,
        arguments=json.loads(operation.arguments_json),
        run_id=RUN_ID,
        generation_id=GENERATION_ID,
        identity_hash=canonical_json_hash(IDENTITY),
        confirmation_hash=research_approval_confirmation_hash("c" * 64, APPROVAL_TOKEN),
        query_plan_hash=QUERY_PLAN.content_hash,
        approval_token=APPROVAL_TOKEN,
        approved_manifest_hash=approval.approved_manifest_hash,
        live_lease=True,
        authorized_query_ids={operation.query_id},
        executed_query_ids=set(),
        authorized_evidence_ids=set(),
    )


def test_required_worker_without_any_operation_rejects_the_whole_manifest():
    from copy import deepcopy

    state = _state()
    identity = deepcopy(IDENTITY)
    identity["destinations"][0]["country_code"] = ""
    state.controlled_trip_identity = identity
    manifest, approval, limitations = compile_and_approve_research_operations(
        state, approval_token=APPROVAL_TOKEN,
    )
    assert manifest is None and approval is None
    assert "accommodation_researcher:no_compiled_operation" in limitations


def test_rail_operations_do_not_hide_missing_local_transport_operations():
    assignments = {
        **ASSIGNMENTS,
        "transport_researcher": {
            **ASSIGNMENTS["transport_researcher"],
            "research_query_ids": ["q_rail", "q_local"],
        },
    }
    manifest, approval, limitations = compile_and_approve_research_operations(
        _state(assignments=assignments), approval_token=APPROVAL_TOKEN,
    )
    assert manifest is None and approval is None
    assert "transport_researcher:local_transport:no_compiled_operation" in limitations
