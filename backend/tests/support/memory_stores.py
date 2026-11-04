"""测试用内存仓储实现。

与产品模块中的 SQL 仓储接口一致；仅测试使用，产品代码不得导入。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from travel_agent.config.models import ModelPricingItem
from travel_agent.llm.usage import LLMCallRecord
from travel_agent.planning.delivery.bundle import DeliveryBundle
from travel_agent.runtime.local_identity import LOCAL_USER_ID
from travel_agent.runtime.run_contracts import (
    TripRun,
    TripRunDetail,
    TripRunEvent,
    TripRunMode,
    TripRunResumePolicy,
    TripRunState,
    TripRunStatus,
    coerce_mode,
    coerce_resume_policy,
    coerce_status,
    generate_trip_run_id,
)
from travel_agent.runtime.run_lifecycle import (
    assert_status_transition_allowed,
    is_terminal_status,
    mark_cancelled_pending_choice,
    with_pending_choice_summary,
)
from travel_agent.runtime.time import utc_now_iso
from travel_agent.storage.cost_ledger_store import (
    CostLedgerStore,
    LLMCostCall,
    _assert_ledger_idempotent,
    build_ledger_call,
    summarize_calls,
)
from travel_agent.storage.delivery_bundle_store import (
    BundleCommitKind,
    BundleCommitRecord,
    BundleCommitResult,
    BundleIdempotencyMismatch,
    BundleRevisionConflict,
    BundleRevisionReuse,
    BundleRevisionVector,
    DeliveryBundleStore,
    FailureInjector,
    PersistBoundary,
    _request_digest,
    _validate_transition,
)
from travel_agent.storage.tool_audit_store import (
    ToolAuditStore,
    _assert_audit_idempotent,
    build_audit_record_from_envelope,
    sanitize_audit_metadata,
)
from travel_agent.storage.trip_run_store import (
    DeliveryCompletionBoundary,
    TripRunEventWindow,
    TripRunFailureInjector,
    TripRunStore,
    _validated_delivery_manifest,
)
from travel_agent.storage.worker_journal_store import TOOL_BUDGET_SCOPE, JournalConflict
from travel_agent.tools.gateway_contracts import ToolAuditRecord


class InMemoryWorkerJournalStore:
    """故障注入用的内存实现；生产环境不会回退到它。"""
    def __init__(self):
        self.rows = {}

    async def load(self, run_id, scope_id):
        return deepcopy(self.rows.get((run_id, scope_id), (0, {})))

    async def reserve_tool(self, run_id, tool_name, *, lease_token=None, limit=None, retry=False):
        # 模拟 Run 创建时初始化的预算；租约仍由生产仓储验证。
        key = run_id, TOOL_BUDGET_SCOPE
        version, payload = self.rows.get(key, (1, {"calls": 0, "retries": {}}))
        calls = int(payload.get("calls") or 0)
        if limit is not None and calls >= limit:
            return None
        retries = dict(payload.get("retries") or {})
        if retry:
            retries[tool_name] = int(retries.get(tool_name) or 0) + 1
        payload = {"calls": calls + 1, "retries": retries}
        self.rows[key] = version + 1, payload
        return deepcopy(payload)

    async def save(self, run_id, scope_id, version, payload, *, lease_token=None):
        key = run_id, scope_id
        if self.rows.get(key, (0, {}))[0] != version:
            raise JournalConflict("concurrent worker journal write")
        self.rows[key] = version + 1, deepcopy(payload)
        return version + 1


class InMemoryToolAuditStore(ToolAuditStore):
    """内存工具审计仓储，保持 audit_id 幂等语义。"""

    def __init__(self) -> None:
        self.records: Dict[str, ToolAuditRecord] = {}

    async def record_envelope(self, envelope: Dict[str, Any], **kwargs: Any) -> ToolAuditRecord:
        # 调用方漏传必需的 manifest 时立即报错。
        if "manifest" not in kwargs:
            raise KeyError("manifest")
        record = build_audit_record_from_envelope(envelope, **kwargs)
        if record.audit_id in self.records:
            existing = self.records[record.audit_id]
            _assert_audit_idempotent(existing, record)
            return existing
        record.metadata = sanitize_audit_metadata(record.metadata)
        self.records[record.audit_id] = record
        return record

    async def list_by_run(self, run_id: str, *, limit: int = 100) -> List[ToolAuditRecord]:
        records = [record for record in self.records.values() if record.run_id == run_id]
        records.sort(key=lambda record: record.created_at, reverse=True)
        return records[: max(1, min(limit, 200))]


class InMemoryCostLedgerStore(CostLedgerStore):
    """内存成本台账，提供相同的异步接口。"""

    def __init__(self) -> None:
        self.calls: List[LLMCostCall] = []
        self._ids: set[str] = set()

    async def record_calls(
        self,
        batch: List[LLMCallRecord],
        *,
        pricing: Optional[List[ModelPricingItem]] = None,
    ) -> List[LLMCostCall]:
        ledger = [build_ledger_call(rec, pricing=pricing) for rec in batch if rec and rec.run_id]
        inserted: List[LLMCostCall] = []
        for call in ledger:
            if call.id in self._ids:
                existing = next(c for c in self.calls if c.id == call.id)
                _assert_ledger_idempotent(existing, call)
                continue  # 幂等：同 id 同内容不重复落
            self._ids.add(call.id)
            self.calls.append(call)
            inserted.append(call)
        return inserted

    def _run_calls(self, run_id: str) -> List[LLMCostCall]:
        rows = [call for call in self.calls if call.run_id == run_id]
        rows.sort(key=lambda c: (c.start_ts or "", c.id))
        return rows

    async def list_calls(
        self,
        run_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> List[LLMCostCall]:
        rows = self._run_calls(run_id)
        start = max(0, offset)
        return rows[start : start + max(1, min(limit, 500))]

    async def run_summary(self, run_id: str) -> Dict[str, Any]:
        return summarize_calls(run_id, self._run_calls(run_id))


class InMemoryDeliveryBundleStore(DeliveryBundleStore):
    """事务语义与 SQL 实现一致的内存参考实现，供 reducer/store 测试使用。"""

    def __init__(self, *, failure_injector: Optional[FailureInjector] = None) -> None:
        super().__init__(failure_injector=failure_injector)
        self._bundles: Dict[str, DeliveryBundle] = {}
        self._heads: Dict[str, str] = {}
        self._commits: Dict[
            tuple[str, str],
            tuple[str, str, Dict[str, Any], BundleCommitKind],
        ] = {}
        self._workspace_revisions: Dict[tuple[str, int], str] = {}
        self._fact_revisions: Dict[tuple[str, int], str] = {}
        self._weather_revisions: Dict[tuple[str, int], str] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def snapshot_for_initial_delivery(self) -> tuple[
        Dict[str, DeliveryBundle],
        Dict[str, str],
        Dict[tuple[str, str], tuple[str, str, Dict[str, Any], BundleCommitKind]],
        Dict[tuple[str, int], str],
        Dict[tuple[str, int], str],
        Dict[tuple[str, int], str],
    ]:
        """只捕获可变持久化状态，供测试事务统一回滚。"""

        return (
            deepcopy(self._bundles),
            deepcopy(self._heads),
            deepcopy(self._commits),
            deepcopy(self._workspace_revisions),
            deepcopy(self._fact_revisions),
            deepcopy(self._weather_revisions),
        )

    def restore_initial_delivery(
        self,
        snapshot: tuple[
            Dict[str, DeliveryBundle],
            Dict[str, str],
            Dict[tuple[str, str], tuple[str, str, Dict[str, Any], BundleCommitKind]],
            Dict[tuple[str, int], str],
            Dict[tuple[str, int], str],
            Dict[tuple[str, int], str],
        ],
    ) -> None:
        (
            self._bundles,
            self._heads,
            self._commits,
            self._workspace_revisions,
            self._fact_revisions,
            self._weather_revisions,
        ) = snapshot

    async def get_current(self, run_id: str) -> Optional[DeliveryBundle]:
        bundle_id = self._heads.get(run_id)
        return self._bundles.get(bundle_id) if bundle_id else None

    async def get_current_bundle_id(self, run_id: str) -> Optional[str]:
        return self._heads.get(run_id)

    async def get_commit(self, run_id: str, idempotency_key: str) -> Optional[BundleCommitRecord]:
        existing = self._commits.get((run_id, idempotency_key))
        if existing is None:
            return None
        _, bundle_id, metadata, _ = existing
        return BundleCommitRecord(
            result=BundleCommitResult(bundle=self._bundles[bundle_id], idempotent_replay=True),
            metadata=metadata,
        )

    async def record_noop_receipt(
        self,
        *,
        run_id: str,
        idempotency_key: str,
        expected: BundleRevisionVector,
        kind: BundleCommitKind,
        idempotency_request: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BundleCommitResult:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        if not expected.bundle_id:
            raise ValueError("no-op receipt requires an expected bundle")
        if kind is not BundleCommitKind.WEATHER_REFRESH_RECEIPT:
            raise ValueError("unsupported no-op receipt kind")
        metadata = metadata or {}
        digest = _request_digest(
            bundle=None,
            kind=kind,
            expected=expected,
            metadata=metadata,
            idempotency_request=idempotency_request,
        )
        lock = self._locks.setdefault(run_id, asyncio.Lock())
        async with lock:
            commit_key = (run_id, idempotency_key)
            existing = self._commits.get(commit_key)
            if existing:
                existing_digest, bundle_id, _, _ = existing
                if existing_digest != digest:
                    raise BundleIdempotencyMismatch("idempotency key was used for another commit")
                return BundleCommitResult(
                    bundle=self._bundles[bundle_id], idempotent_replay=True
                )
            current_bundle = await self.get_current(run_id)
            current = (
                BundleRevisionVector.from_bundle(current_bundle)
                if current_bundle is not None
                else None
            )
            if current != expected:
                raise BundleRevisionConflict(current)
            self._inject(PersistBoundary.IDEMPOTENCY_RECORD)
            self._commits = {
                **self._commits,
                commit_key: (
                    digest,
                    expected.bundle_id,
                    metadata,
                    kind,
                ),
            }
            return BundleCommitResult(bundle=current_bundle)

    async def commit(
        self,
        *,
        bundle: DeliveryBundle,
        kind: BundleCommitKind,
        idempotency_key: str,
        expected: Optional[BundleRevisionVector] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_request: Optional[Dict[str, Any]] = None,
    ) -> BundleCommitResult:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        _validate_transition(
            bundle=bundle,
            kind=kind,
            expected=expected,
        )
        metadata = metadata or {}
        run_id = bundle.manifest.run_id
        digest = _request_digest(
            bundle=bundle,
            kind=kind,
            expected=expected,
            metadata=metadata,
            idempotency_request=idempotency_request,
        )
        lock = self._locks.setdefault(run_id, asyncio.Lock())
        async with lock:
            commit_key = (run_id, idempotency_key)
            existing = self._commits.get(commit_key)
            if existing:
                existing_digest, bundle_id, _, _ = existing
                if existing_digest != digest:
                    raise BundleIdempotencyMismatch("idempotency key was used for another commit")
                return BundleCommitResult(bundle=self._bundles[bundle_id], idempotent_replay=True)

            current_bundle = await self.get_current(run_id)
            current = BundleRevisionVector.from_bundle(current_bundle) if current_bundle else None
            if kind == BundleCommitKind.CREATE:
                if current is not None:
                    raise BundleRevisionConflict(current)
            elif current != expected:
                raise BundleRevisionConflict(current)

            bundles = dict(self._bundles)
            heads = dict(self._heads)
            commits = dict(self._commits)
            workspace_revisions = dict(self._workspace_revisions)
            fact_revisions = dict(self._fact_revisions)
            weather_revisions = dict(self._weather_revisions)

            self._stage_revision(
                workspace_revisions,
                (run_id, bundle.manifest.workspace_revision),
                bundle.manifest.content_hashes["workspace"],
            )
            self._inject(PersistBoundary.WORKSPACE_SNAPSHOT)
            self._stage_revision(
                fact_revisions,
                (run_id, bundle.manifest.fact_data_revision),
                bundle.manifest.content_hashes["fact_snapshot"],
            )
            self._inject(PersistBoundary.FACT_SNAPSHOT)
            self._stage_revision(
                weather_revisions,
                (run_id, bundle.manifest.weather_data_revision),
                bundle.manifest.content_hashes["weather_snapshot"],
            )
            self._inject(PersistBoundary.WEATHER_SNAPSHOT)

            if bundle.manifest.bundle_id in bundles:
                raise BundleRevisionReuse("bundle id already exists")
            vector = BundleRevisionVector.from_bundle(bundle)
            if any(
                (
                    item.manifest.workspace_revision,
                    item.manifest.fact_data_revision,
                    item.manifest.weather_data_revision,
                )
                == (
                    vector.workspace_revision,
                    vector.fact_data_revision,
                    vector.weather_data_revision,
                )
                for item in bundles.values()
                if item.manifest.run_id == run_id
            ):
                raise BundleRevisionReuse("bundle revision vector already exists")
            bundles[bundle.manifest.bundle_id] = bundle
            self._inject(PersistBoundary.BUNDLE)
            heads[run_id] = bundle.manifest.bundle_id
            self._inject(PersistBoundary.CURRENT_POINTER)
            commits[commit_key] = (
                digest,
                bundle.manifest.bundle_id,
                metadata,
                kind,
            )
            self._inject(PersistBoundary.IDEMPOTENCY_RECORD)

            self._bundles = bundles
            self._heads = heads
            self._commits = commits
            self._workspace_revisions = workspace_revisions
            self._fact_revisions = fact_revisions
            self._weather_revisions = weather_revisions
            return BundleCommitResult(bundle=bundle)

    @staticmethod
    def _stage_revision(
        revisions: Dict[tuple[str, int], str],
        key: tuple[str, int],
        content_hash: str,
    ) -> None:
        existing = revisions.get(key)
        if existing is not None and existing != content_hash:
            raise BundleRevisionReuse(f"revision {key} already contains different content")
        revisions[key] = content_hash


class InMemoryTripRunStore(TripRunStore):
    """内存 TripRun 仓储，提供相同的异步接口。"""

    def __init__(
        self,
        *,
        failure_injector: Optional[TripRunFailureInjector] = None,
    ) -> None:
        super().__init__(failure_injector=failure_injector)
        self.runs: Dict[str, TripRun] = {}
        self.states: Dict[str, TripRunState] = {}
        self.events: Dict[str, List[TripRunEvent]] = defaultdict(list)

    @asynccontextmanager
    async def transaction(self, run_id: str):
        run = deepcopy(self.runs.get(run_id))
        state = deepcopy(self.states.get(run_id))
        events = deepcopy(self.events.get(run_id))
        try:
            yield None
        except BaseException:
            if run is not None:
                self.runs[run_id] = run
            if state is not None:
                self.states[run_id] = state
            if events is not None:
                self.events[run_id] = events
            raise

    def snapshot_for_initial_delivery(
        self,
    ) -> tuple[Dict[str, TripRun], Dict[str, TripRunState], Dict[str, List[TripRunEvent]]]:
        """捕获可变生命周期状态，供测试事务统一回滚。"""

        return (
            deepcopy(self.runs),
            deepcopy(self.states),
            deepcopy(dict(self.events)),
        )

    def restore_initial_delivery(
        self,
        snapshot: tuple[
            Dict[str, TripRun],
            Dict[str, TripRunState],
            Dict[str, List[TripRunEvent]],
        ],
    ) -> None:
        runs, states, events = snapshot
        self.runs = runs
        self.states = states
        self.events = defaultdict(list, events)

    async def create_run(
        self,
        *,
        session_id: str,
        user_id: str,
        mode: str | TripRunMode,
        request_message_id: str = "",
        assistant_message_id: str = "",
        run_id: Optional[str] = None,
        parent_run_id: Optional[str] = None,
        resume_policy: str | TripRunResumePolicy = TripRunResumePolicy.CLARIFY_ONLY,
        controlled_trip_identity: Optional[Dict[str, Any]] = None,
        route_decision: Optional[Dict[str, Any]] = None,
    ) -> TripRun:
        run = TripRun(
            run_id=run_id or generate_trip_run_id(),
            session_id=session_id,
            user_id=user_id or LOCAL_USER_ID,
            mode=coerce_mode(mode),
            request_message_id=request_message_id,
            assistant_message_id=assistant_message_id,
            parent_run_id=parent_run_id,
            resume_policy=coerce_resume_policy(resume_policy),
            controlled_trip_identity=controlled_trip_identity,
        )
        if run.run_id in self.runs:
            existing = self.runs[run.run_id]
            if run_id is not None and existing.user_id == run.user_id and existing.session_id == session_id and existing.request_message_id == request_message_id:
                return existing
            raise ValueError(f"TripRun already exists: {run.run_id}")
        self.runs[run.run_id] = run
        initial_summary = {
            "route_decision": route_decision,
            "identity_locked": bool(controlled_trip_identity),
        }
        self.states[run.run_id] = TripRunState(
            run_id=run.run_id,
            status=run.status,
            latest_state_summary=initial_summary,
        )
        await self.append_event(
            run.run_id,
            "run.created",
            {
                "mode": run.mode.value,
                "session_id": run.session_id,
                "user_id": run.user_id,
                "resume_policy": run.resume_policy.value,
                "route_decision": route_decision,
            },
        )
        return run

    async def get_run(self, run_id: str) -> Optional[TripRun]:
        return self.runs.get(run_id)

    async def update_controlled_trip_identity(
        self, run_id: str, *, controlled_trip_identity: Dict[str, Any]
    ) -> None:
        run = self.runs.get(run_id)
        if run is None:
            raise KeyError(f"TripRun not found: {run_id}")
        self.runs[run_id] = run.model_copy(
            update={"controlled_trip_identity": controlled_trip_identity}
        )

    async def get_detail(self, run_id: str, *, event_limit: int = 50) -> Optional[TripRunDetail]:
        run = self.runs.get(run_id)
        state = self.states.get(run_id)
        if not run or not state:
            return None
        return TripRunDetail(
            run=run,
            state=state,
            events=list(self.events.get(run_id, []))[-event_limit:],
        )

    async def list_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> List[TripRunEvent]:
        if run_id not in self.runs:
            raise KeyError(f"TripRun not found: {run_id}")
        return [
            event
            for event in self.events[run_id]
            if event.sequence > max(0, after_sequence)
        ][: max(1, min(limit, 500))]

    async def list_delivery_events(
        self,
        run_id: str,
        bundle_id: str,
    ) -> List[TripRunEvent]:
        if run_id not in self.runs:
            raise KeyError(f"TripRun not found: {run_id}")
        return [
            event
            for event in self.events[run_id]
            if event.event_type in {"delivery.ready", "run.terminal"}
            and event.payload.get("bundle_id") == bundle_id
        ]

    async def read_event_window(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
        retention_events: int = 500,
    ) -> TripRunEventWindow:
        if run_id not in self.runs:
            raise KeyError(f"TripRun not found: {run_id}")
        after_sequence = max(0, after_sequence)
        limit = max(1, min(limit, 500))
        retention_events = max(1, min(retention_events, 5000))
        all_events = self.events[run_id]
        latest = all_events[-1].sequence if all_events else 0
        first = all_events[0].sequence if all_events else 0
        floor = max(first, latest - retention_events + 1) if latest else 0
        expired = after_sequence > 0 and floor > 0 and after_sequence < floor - 1
        events = [] if expired else [
            event
            for event in all_events
            if event.sequence > after_sequence and event.sequence >= floor
        ][:limit]
        return TripRunEventWindow(
            events=events,
            requested_after_sequence=after_sequence,
            replay_floor_sequence=floor,
            latest_sequence=latest,
            window_expired=expired,
        )

    async def list_runs(
        self,
        *,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        status: Optional[str | TripRunStatus] = None,
        mode: Optional[str | TripRunMode] = None,
        limit: int = 50,
    ) -> List[TripRun]:
        status_value = coerce_status(status).value if status else None
        mode_value = coerce_mode(mode).value if mode else None
        runs = list(self.runs.values())
        if user_id:
            runs = [run for run in runs if run.user_id == user_id]
        if session_id:
            runs = [run for run in runs if run.session_id == session_id]
        if status_value:
            runs = [run for run in runs if run.status.value == status_value]
        if mode_value:
            runs = [run for run in runs if run.mode.value == mode_value]
        runs.sort(key=lambda run: run.updated_at, reverse=True)
        return runs[: max(1, min(limit, 200))]

    async def count_runs(
        self,
        *,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        status: Optional[str | TripRunStatus] = None,
        mode: Optional[str | TripRunMode] = None,
    ) -> int:
        status_value = coerce_status(status).value if status else None
        mode_value = coerce_mode(mode).value if mode else None
        runs = list(self.runs.values())
        if user_id:
            runs = [run for run in runs if run.user_id == user_id]
        if session_id:
            runs = [run for run in runs if run.session_id == session_id]
        if status_value:
            runs = [run for run in runs if run.status.value == status_value]
        if mode_value:
            runs = [run for run in runs if run.mode.value == mode_value]
        return len(runs)

    async def list_run_titles(self, session_ids: List[str], *, max_len: int = 60) -> Dict[str, str]:
        # 内存实现没有 chat 事件表；生产环境的标题来自 SQL 路径。
        return {}

    async def transition_status(
        self,
        run_id: str,
        target_status: str | TripRunStatus,
        *,
        current_node: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        pending_user_choice: Optional[Dict[str, Any]] = None,
        event_type: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        allow_same: bool = True,
        db_session: Any = None,
        execution_lease_token: Optional[str] = None,
    ) -> TripRun:
        run = self.runs.get(run_id)
        if run is None:
            raise KeyError(f"TripRun not found: {run_id}")
        target = coerce_status(target_status)
        assert_status_transition_allowed(run.status, target, allow_same=allow_same)
        if target == TripRunStatus.COMPLETED and run.mode == TripRunMode.DEEP:
            raise ValueError(
                "deep TripRun completion requires complete_delivery() so the Bundle, "
                "delivery.ready, and run.terminal remain one atomic boundary"
            )
        now = utc_now_iso()
        previous = run.status
        attempt_increment = (
            1
            if target == TripRunStatus.RUNNING
            and previous in {TripRunStatus.FAILED, TripRunStatus.INTERRUPTED}
            else 0
        )
        run.status = target
        run.current_node = current_node or run.current_node
        run.last_error_code = error_code
        run.last_error_message = error_message
        run.attempt += attempt_increment
        run.updated_at = now
        if target == TripRunStatus.RUNNING and not run.started_at:
            run.started_at = now
        if target == TripRunStatus.COMPLETED:
            run.completed_at = now
        if target == TripRunStatus.CANCELLED:
            run.cancelled_at = now

        state = self.states[run_id]
        state.status = target
        state.current_node = current_node or state.current_node
        state.pending_user_choice = (
            mark_cancelled_pending_choice(pending_user_choice or state.pending_user_choice)
            if target == TripRunStatus.CANCELLED
            else pending_user_choice
        )
        if state.pending_user_choice or target != TripRunStatus.AWAITING_INPUT:
            state.latest_state_summary = with_pending_choice_summary(
                state.latest_state_summary,
                pending=bool(state.pending_user_choice) and target == TripRunStatus.AWAITING_INPUT,
            )
        state.last_error = (
            {"code": error_code or "error", "message": error_message or ""}
            if error_code or error_message
            else None
        )
        state.updated_at = now
        await self.append_event(
            run_id,
            event_type or f"run.{target.value}",
            {
                "from_status": previous.value,
                "to_status": target.value,
                **(payload or {}),
                **({"current_node": current_node} if current_node else {}),
                **({"last_error": state.last_error} if state.last_error else {}),
            },
        )
        return run

    async def complete_delivery(
        self,
        run_id: str,
        *,
        bundle_id: str,
        manifest: Dict[str, Any],
        current_node: str = "delivery_finalizer",
        execution_lease_token: Optional[str] = None,
    ) -> tuple[TripRun, TripRunEvent, TripRunEvent]:
        manifest_payload = _validated_delivery_manifest(
            run_id=run_id,
            bundle_id=bundle_id,
            manifest=manifest,
        )
        run = self.runs.get(run_id)
        if run is None:
            raise KeyError(f"TripRun not found: {run_id}")
        state = self.states.get(run_id)
        if state is None:
            raise KeyError(f"TripRunState not found: {run_id}")
        existing = [
            event
            for event in self.events[run_id]
            if event.event_type in {"delivery.ready", "run.terminal"}
        ]
        if run.status == TripRunStatus.COMPLETED:
            ready_events = [
                event for event in existing if event.event_type == "delivery.ready"
            ]
            terminal_events = [
                event for event in existing if event.event_type == "run.terminal"
            ]
            if (
                len(ready_events) != 1
                or len(terminal_events) != 1
                or ready_events[0].payload.get("bundle_id") != bundle_id
                or terminal_events[0].payload.get("bundle_id") != bundle_id
                or ready_events[0].payload.get("manifest") != manifest_payload
                or terminal_events[0].payload.get("manifest") != manifest_payload
                or ready_events[0].sequence >= terminal_events[0].sequence
            ):
                raise RuntimeError("completed delivery events are missing or duplicated")
            return run, ready_events[0], terminal_events[0]
        assert_status_transition_allowed(
            run.status,
            TripRunStatus.COMPLETED,
            allow_same=False,
        )
        if existing:
            raise RuntimeError("non-completed run already exposes delivery events")

        run_before = deepcopy(run)
        state_before = deepcopy(self.states[run_id])
        events_before = list(self.events[run_id])
        try:
            ready_event = await self.append_event(
                run_id,
                "delivery.ready",
                {
                    "bundle_id": bundle_id,
                    "manifest": manifest_payload,
                    "idempotency_key": f"{run_id}:delivery_ready:{bundle_id}",
                },
            )
            self._inject(DeliveryCompletionBoundary.READY_EVENT)
            previous = run.status
            now = utc_now_iso()
            run.status = TripRunStatus.COMPLETED
            run.current_node = current_node
            run.last_error_code = None
            run.last_error_message = None
            run.completed_at = now
            run.updated_at = now
            state.status = TripRunStatus.COMPLETED
            state.current_node = current_node
            state.pending_user_choice = None
            state.last_error = None
            state.latest_state_summary = with_pending_choice_summary(
                state.latest_state_summary,
                pending=False,
            )
            state.updated_at = now
            self._inject(DeliveryCompletionBoundary.COMPLETED_STATUS)
            terminal_event = await self.append_event(
                run_id,
                "run.terminal",
                {
                    "from_status": previous.value,
                    "to_status": TripRunStatus.COMPLETED.value,
                    "status": TripRunStatus.COMPLETED.value,
                    "bundle_id": bundle_id,
                    "manifest": manifest_payload,
                    "delivery_event_sequence": ready_event.sequence,
                    "current_node": current_node,
                    "idempotency_key": f"{run_id}:run_terminal:{bundle_id}",
                },
            )
            self._inject(DeliveryCompletionBoundary.TERMINAL_EVENT)
            return run, ready_event, terminal_event
        except Exception:
            self.runs[run_id] = run_before
            self.states[run_id] = state_before
            self.events[run_id] = events_before
            raise

    async def claim_checkpoint_resume(
        self,
        run_id: str,
        *,
        allowed_statuses: Optional[List[str | TripRunStatus]] = None,
        current_node: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Optional[TripRun]:
        run = self.runs.get(run_id)
        if run is None:
            raise KeyError(f"TripRun not found: {run_id}")
        statuses = {
            coerce_status(status)
            for status in (allowed_statuses or [TripRunStatus.FAILED, TripRunStatus.INTERRUPTED])
        }
        if run.status not in statuses or run.resume_policy != TripRunResumePolicy.CHECKPOINT:
            return None

        previous = run.status
        now = utc_now_iso()
        run.status = TripRunStatus.RUNNING
        run.current_node = current_node or run.current_node
        run.last_error_code = None
        run.last_error_message = None
        run.attempt += 1
        run.updated_at = now
        if not run.started_at:
            run.started_at = now

        state = self.states[run_id]
        state.status = TripRunStatus.RUNNING
        state.current_node = current_node or state.current_node
        state.pending_user_choice = None
        state.latest_state_summary = with_pending_choice_summary(
            state.latest_state_summary,
            pending=False,
        )
        state.last_error = None
        state.updated_at = now
        await self.append_event(
            run_id,
            "run.resumed",
            {
                "from_status": previous.value,
                "to_status": TripRunStatus.RUNNING.value,
                "resume_policy": TripRunResumePolicy.CHECKPOINT.value,
                "attempt": run.attempt,
                **(payload or {}),
                **({"current_node": current_node} if current_node else {}),
            },
        )
        return run

    async def list_checkpoint_prune_candidates(
        self,
        *,
        completed_days: int = 30,
        cancelled_days: int = 30,
        failed_interrupted_days: int = 90,
        limit: int = 100,
    ) -> List[TripRun]:
        now = datetime.now(timezone.utc)

        def _older_than(run: TripRun, days: int) -> bool:
            try:
                updated = datetime.fromisoformat(run.updated_at)
            except Exception:
                return False
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            return updated < now - timedelta(days=max(0, days))

        candidates: List[TripRun] = []
        for run in self.runs.values():
            if run.resume_policy != TripRunResumePolicy.CHECKPOINT:
                continue
            if run.status == TripRunStatus.COMPLETED and _older_than(run, completed_days):
                candidates.append(run)
            elif run.status == TripRunStatus.CANCELLED and _older_than(run, cancelled_days):
                candidates.append(run)
            elif run.status in {TripRunStatus.FAILED, TripRunStatus.INTERRUPTED} and _older_than(
                run, failed_interrupted_days
            ):
                candidates.append(run)
        candidates.sort(key=lambda run: run.updated_at)
        return candidates[: max(1, min(limit, 1000))]

    async def record_node_lifecycle(
        self,
        run_id: str,
        *,
        node: str,
        status: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Optional[TripRunEvent]:
        if not node.strip():
            raise ValueError("Node lifecycle requires a node name")
        if status not in {"started", "completed", "retrying", "failed"}:
            raise ValueError(f"Unsupported node lifecycle status: {status}")
        run = self.runs.get(run_id)
        state = self.states.get(run_id)
        if run is None or state is None:
            raise KeyError(f"TripRun not found: {run_id}")
        if is_terminal_status(run.status):
            return None
        if status == "started":
            if run.status != TripRunStatus.RUNNING:
                return None
            now = utc_now_iso()
            run.current_node = node
            run.updated_at = now
            state.current_node = node
            state.updated_at = now
        return await self.append_event(
            run_id,
            f"node.{status}",
            {**(payload or {}), "node": node, "status": status},
        )

    async def record_node_update(
        self,
        run_id: str,
        *,
        node: str,
        trace_event_count: Optional[int] = None,
    ) -> TripRunState:
        state = self.states.get(run_id)
        run = self.runs.get(run_id)
        if state is None or run is None:
            raise KeyError(f"TripRunState not found: {run_id}")
        if node and node not in state.completed_nodes:
            state.completed_nodes.append(node)
        if is_terminal_status(run.status):
            state.pending_user_choice = (
                mark_cancelled_pending_choice(state.pending_user_choice)
                if run.status == TripRunStatus.CANCELLED
                else None
            )
        state.latest_state_summary = with_pending_choice_summary(
            state.latest_state_summary,
            pending=bool(state.pending_user_choice) and not is_terminal_status(run.status),
        )
        if trace_event_count is not None:
            state.trace_event_count = trace_event_count
        state.updated_at = utc_now_iso()
        run.updated_at = state.updated_at
        return state

    async def record_state_summary(
        self,
        run_id: str,
        *,
        summary: Dict[str, Any],
    ) -> TripRunState:
        state = self.states.get(run_id)
        run = self.runs.get(run_id)
        if state is None or run is None:
            raise KeyError(f"TripRunState not found: {run_id}")
        state.latest_state_summary = with_pending_choice_summary(
            summary,
            pending=(
                run.status == TripRunStatus.AWAITING_INPUT
                and bool(state.pending_user_choice)
            ),
        )
        state.updated_at = utc_now_iso()
        run.updated_at = state.updated_at
        return state

    async def append_event(self, run_id: str, event_type: str, payload: Dict[str, Any]) -> TripRunEvent:
        if run_id not in self.runs:
            raise KeyError(f"TripRun not found: {run_id}")
        event = TripRunEvent(
            event_id=len(self.events[run_id]) + 1,
            run_id=run_id,
            sequence=len(self.events[run_id]) + 1,
            event_type=event_type,
            payload=payload,
        )
        self.events[run_id].append(event)
        return event

    async def append_event_once(
        self,
        run_id: str,
        event_type: str,
        payload: Dict[str, Any],
        *,
        idempotency_key: str,
    ) -> TripRunEvent:
        if not idempotency_key.strip():
            raise ValueError("event idempotency_key is required")
        durable_payload = {**payload, "idempotency_key": idempotency_key}
        for event in self.events.get(run_id, []):
            if event.payload.get("idempotency_key") != idempotency_key:
                continue
            if event.event_type != event_type or event.payload != durable_payload:
                raise ValueError("event idempotency key was used for another payload")
            return event
        return await self.append_event(run_id, event_type, durable_payload)

    async def request_cancel(
        self,
        run_id: str,
        *,
        current_node: Optional[str] = None,
        event_type: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> TripRun:
        for _ in range(3):
            run = self.runs.get(run_id)
            if run is None:
                raise KeyError(f"TripRun not found: {run_id}")
            target = (
                TripRunStatus.CANCEL_REQUESTED
                if run.status == TripRunStatus.RUNNING
                else TripRunStatus.CANCELLED
                if run.status in {
                    TripRunStatus.CREATED,
                    TripRunStatus.AWAITING_INPUT,
                    TripRunStatus.CANCEL_REQUESTED,
                }
                else None
            )
            if target is None:
                return run
            try:
                return await self.transition_status(
                    run_id,
                    target,
                    current_node=current_node,
                    event_type=event_type,
                    payload=payload,
                )
            except ValueError:
                continue
        run = self.runs[run_id]
        if run.status in {
            TripRunStatus.CREATED,
            TripRunStatus.RUNNING,
            TripRunStatus.AWAITING_INPUT,
            TripRunStatus.CANCEL_REQUESTED,
        }:
            raise RuntimeError(f"TripRun cancellation did not converge: {run_id}")
        return run
