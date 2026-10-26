"""不可变交付 Bundle 的原子持久化。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional

from sqlalchemy import text

from travel_agent.planning.delivery.bundle import (
    DELIVERY_BUNDLE_CONTRACT_VERSION,
    DeliveryBundle,
)

from .database import get_db_session

FailureInjector = Callable[[str], None]


class BundleContractSuperseded(RuntimeError):
    """已存 Bundle 的合同版本与当前代码不一致。

    先从行内的 ``manifest`` JSONB 列读取版本标记并在解析载荷之前比较。直接解析
    会在深层字段抛 ``ValidationError``，应用内没有处理器，最终变成一次普通产品
    读取的 500 错误。版本标记只需一次比较就能给出同样的结论，并说明该行写入时
    使用的合同版本。

    遇到不匹配时拒绝读取，不做兼容分发：旧结构如何处置是一次性的数据决策，
    不是常驻代码路径。
    """

    def __init__(self, *, run_id: str, stored: Optional[str]) -> None:
        super().__init__(
            f"delivery bundle for run {run_id} was stored under contract "
            f"{stored or 'unknown'}, which {DELIVERY_BUNDLE_CONTRACT_VERSION} supersedes"
        )
        self.run_id = run_id
        self.stored = stored


class BundleCommitKind(str, Enum):
    CREATE = "create"
    WORKSPACE_MUTATION = "workspace_mutation"
    WORKSPACE_MUTATION_RECEIPT = "workspace_mutation_receipt"
    FACT_REFRESH = "fact_refresh"
    WEATHER_REFRESH = "weather_refresh"
    WEATHER_REFRESH_RECEIPT = "weather_refresh_receipt"
    WEATHER_FACT_REFRESH = "weather_fact_refresh"
    UNDO = "undo"


class PersistBoundary(str, Enum):
    WORKSPACE_SNAPSHOT = "workspace_snapshot"
    FACT_SNAPSHOT = "fact_snapshot"
    WEATHER_SNAPSHOT = "weather_snapshot"
    BUNDLE = "bundle"
    CURRENT_POINTER = "current_pointer"
    IDEMPOTENCY_RECORD = "idempotency_record"


@dataclass(frozen=True)
class BundleRevisionVector:
    workspace_revision: int
    fact_data_revision: int
    weather_data_revision: int
    bundle_id: Optional[str] = None

    @classmethod
    def from_bundle(cls, bundle: DeliveryBundle) -> "BundleRevisionVector":
        manifest = bundle.manifest
        return cls(
            workspace_revision=manifest.workspace_revision,
            fact_data_revision=manifest.fact_data_revision,
            weather_data_revision=manifest.weather_data_revision,
            bundle_id=manifest.bundle_id,
        )


@dataclass(frozen=True)
class BundleCommitResult:
    bundle: DeliveryBundle
    idempotent_replay: bool = False


@dataclass(frozen=True)
class BundleCommitRecord:
    result: BundleCommitResult
    inverse_patch: Optional[Dict[str, Any]]
    metadata: Dict[str, Any]


@dataclass(frozen=True)
class BundleUndoHead:
    mutation_id: str
    label: str
    semantic_label: str
    inverse_patch: Dict[str, Any]
    result_bundle_id: str
    workspace_revision: int


class BundleRevisionConflict(RuntimeError):
    def __init__(self, current: Optional[BundleRevisionVector]):
        super().__init__("delivery bundle revision conflict")
        self.current = current


class BundleIdempotencyMismatch(RuntimeError):
    pass


class BundleRevisionReuse(RuntimeError):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


@asynccontextmanager
async def _session_scope(session: Any | None):
    """复用调用方已有的事务，不提前提交。"""

    if session is not None:
        yield session
        return
    async with get_db_session() as owned_session:
        yield owned_session


def _request_digest(
    *,
    bundle: Optional[DeliveryBundle],
    kind: BundleCommitKind,
    expected: Optional[BundleRevisionVector],
    inverse_patch: Optional[Dict[str, Any]],
    metadata: Dict[str, Any],
    idempotency_request: Optional[Dict[str, Any]] = None,
) -> str:
    if idempotency_request is not None:
        # 一条逻辑命令可能落成实体 revision，也可能落成 no-op 回执。它的重放
        # 身份是用户命令本身，而不是先观察到结果的是哪条持久化分支。
        value = {"idempotency_request": idempotency_request}
        return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()
    if bundle is None:
        raise ValueError("bundle is required when no semantic idempotency request is supplied")
    value = {
        "bundle": bundle.model_dump(mode="json"),
        "kind": kind.value,
        "expected": expected.__dict__ if expected else None,
        "inverse_patch": inverse_patch,
        "metadata": metadata,
    }
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _vector_from_row(row: Dict[str, Any]) -> BundleRevisionVector:
    return BundleRevisionVector(
        workspace_revision=int(row["workspace_revision"]),
        fact_data_revision=int(row["fact_data_revision"]),
        weather_data_revision=int(row["weather_data_revision"]),
        bundle_id=str(row["current_bundle_id"]),
    )


def _validate_transition(
    *,
    bundle: DeliveryBundle,
    kind: BundleCommitKind,
    expected: Optional[BundleRevisionVector],
) -> None:
    actual = BundleRevisionVector.from_bundle(bundle)
    if kind == BundleCommitKind.CREATE:
        if expected is not None:
            raise ValueError("create commit cannot have an expected current revision")
        if (actual.workspace_revision, actual.fact_data_revision, actual.weather_data_revision) != (0, 0, 0):
            raise ValueError("initial delivery bundle revisions must all be zero")
    else:
        if expected is None or not expected.bundle_id:
            raise ValueError("non-create commit requires the expected current bundle")
        deltas = (
            actual.workspace_revision - expected.workspace_revision,
            actual.fact_data_revision - expected.fact_data_revision,
            actual.weather_data_revision - expected.weather_data_revision,
        )
        expected_deltas = {
            BundleCommitKind.WORKSPACE_MUTATION: {(1, 0, 0)},
            BundleCommitKind.UNDO: {(1, 0, 0)},
            BundleCommitKind.FACT_REFRESH: {(0, 1, 0)},
            BundleCommitKind.WEATHER_REFRESH: {(0, 0, 1)},
            # 天气与事实联合刷新会把候选目录重绑到新的事实+天气快照，
            # workspace 载荷随之可能变化，因此 workspace 版本允许一并提升。
            BundleCommitKind.WEATHER_FACT_REFRESH: {(0, 1, 1), (1, 1, 1)},
        }[kind]
        if deltas not in expected_deltas:
            raise ValueError(
                f"{kind.value} must advance revisions by one of "
                f"{sorted(expected_deltas)}, got {deltas}"
            )


class DeliveryBundleStore:
    def __init__(self, *, failure_injector: Optional[FailureInjector] = None) -> None:
        self._failure_injector = failure_injector

    def _inject(self, boundary: PersistBoundary) -> None:
        if self._failure_injector:
            self._failure_injector(boundary.value)

    def bundle_from_row(
        self,
        *,
        run_id: str,
        contract_stamp: Optional[str],
        payload: Any,
    ) -> DeliveryBundle:
        """先比较已存版本标记，再解析载荷；所有读取路径都经过这里。

        每次返回已存载荷的读取都走这个入口，新增消费方不会漏掉版本比较。标记与
        载荷在同一行，因此不增加查询次数，也不需要改 schema：
        ``delivery_bundles_v2.manifest`` 本身就是独立的 JSONB 列。
        """

        if contract_stamp != DELIVERY_BUNDLE_CONTRACT_VERSION:
            raise BundleContractSuperseded(run_id=run_id, stored=contract_stamp)
        return DeliveryBundle.model_validate(payload)

    async def get_current(self, run_id: str) -> Optional[DeliveryBundle]:
        async with get_db_session() as session:
            return await self.get_current_in_session(session, run_id)

    async def get_current_in_session(
        self,
        session: Any,
        run_id: str,
    ) -> Optional[DeliveryBundle]:
        result = await session.execute(
            text(
                """
                SELECT bundle.manifest->>'contract_version' AS contract_stamp,
                       bundle.bundle
                FROM delivery_bundle_heads_v2 AS head
                JOIN delivery_bundles_v2 AS bundle
                  ON bundle.bundle_id = head.current_bundle_id
                WHERE head.run_id = :run_id
                """
            ),
            {"run_id": run_id},
        )
        row = result.mappings().first()
        if row is None or row["bundle"] is None:
            return None
        return self.bundle_from_row(
            run_id=run_id,
            contract_stamp=row["contract_stamp"],
            payload=_json_loads(row["bundle"]),
        )

    async def get_current_bundle_id(self, run_id: str) -> Optional[str]:
        """只读取当前 Bundle 身份，不加载也不校验载荷。

        head 行是权威指针，其外键保证引用的 Bundle 存在，因此只需要身份调用方
        （事件窗口、revision 冲突响应）不必解析载荷。写入于旧合同的载荷不应让
        这类读取失败：身份仍然可以确定。
        """
        async with get_db_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT current_bundle_id
                    FROM delivery_bundle_heads_v2
                    WHERE run_id = :run_id
                    """
                ),
                {"run_id": run_id},
            )
            bundle_id = result.scalar_one_or_none()
            return str(bundle_id) if bundle_id is not None else None

    async def get_commit(self, run_id: str, idempotency_key: str) -> Optional[BundleCommitRecord]:
        async with get_db_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT commit.inverse_patch, commit.metadata, bundle.bundle,
                           bundle.manifest->>'contract_version' AS contract_stamp
                    FROM delivery_bundle_commits_v2 AS commit
                    JOIN delivery_bundles_v2 AS bundle
                      ON bundle.bundle_id = commit.result_bundle_id
                    WHERE commit.run_id = :run_id
                      AND commit.idempotency_key = :idempotency_key
                    """
                ),
                {"run_id": run_id, "idempotency_key": idempotency_key},
            )
            row = result.mappings().first()
            if row is None:
                return None
            return BundleCommitRecord(
                result=BundleCommitResult(
                    bundle=self.bundle_from_row(
                        run_id=run_id,
                        contract_stamp=row["contract_stamp"],
                        payload=_json_loads(row["bundle"]),
                    ),
                    idempotent_replay=True,
                ),
                inverse_patch=_json_loads(row["inverse_patch"]),
                metadata=_json_loads(row["metadata"]) or {},
            )

    async def get_undo_head(self, run_id: str) -> Optional[BundleUndoHead]:
        """返回当前语义 workspace head 的服务端 inverse。"""
        async with get_db_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT commit.idempotency_key, commit.inverse_patch,
                           commit.metadata, commit.result_bundle_id,
                           bundle.workspace_revision
                    FROM delivery_bundle_heads_v2 AS head
                    JOIN delivery_bundle_commits_v2 AS commit
                      ON commit.run_id = head.run_id
                    JOIN delivery_bundles_v2 AS bundle
                      ON bundle.bundle_id = commit.result_bundle_id
                    WHERE head.run_id = :run_id
                      -- 天气/事实重绑可能仅为了让当前 Candidate 目录与刷新后的
                      -- 事实对齐而提升不可变 Workspace revision。它不能覆盖最近
                      -- 一个用户发起的 undo head；服务只重新应用可安全变基的
                      -- inverse。
                      AND bundle.workspace_revision <= head.workspace_revision
                      AND commit.inverse_patch IS NOT NULL
                      AND commit.commit_kind IN ('workspace_mutation', 'undo')
                    ORDER BY commit.created_at DESC, commit.result_bundle_id DESC
                    LIMIT 1
                    """
                ),
                {"run_id": run_id},
            )
            row = result.mappings().first()
            if row is None:
                return None
            metadata = _json_loads(row["metadata"]) or {}
            return BundleUndoHead(
                mutation_id=str(row["idempotency_key"]),
                label=str(
                    metadata.get("undo_label")
                    or f"撤销：{metadata.get('label') or '上一步调整'}"
                ),
                semantic_label=str(
                    metadata.get("semantic_label")
                    or metadata.get("label")
                    or "上一步调整"
                ),
                inverse_patch=_json_loads(row["inverse_patch"]),
                result_bundle_id=str(row["result_bundle_id"]),
                workspace_revision=int(row["workspace_revision"]),
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
        session: Any | None = None,
    ) -> BundleCommitResult:
        """持久化一个不改变当前状态的命令回执，供精确重放。

        用户命令没有可用选项，或发现目录已是最新时，仍然需要一个 durable 的
        幂等结果。这里只写台账回执：引用现有当前 Bundle，不执行 snapshot、
        Bundle、head 或 undo 变更。
        """

        if not idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        if not expected.bundle_id:
            raise ValueError("no-op receipt requires an expected bundle")
        if kind not in {
            BundleCommitKind.WORKSPACE_MUTATION_RECEIPT,
            BundleCommitKind.WEATHER_REFRESH_RECEIPT,
        }:
            raise ValueError("unsupported no-op receipt kind")
        metadata = metadata or {}
        digest = _request_digest(
            bundle=None,
            kind=kind,
            expected=expected,
            inverse_patch=None,
            metadata=metadata,
            idempotency_request=idempotency_request,
        )
        async with _session_scope(session) as session:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:run_id, 0))"),
                {"run_id": run_id},
            )
            existing_result = await session.execute(
                text(
                    """
                    SELECT request_digest, result_bundle_id
                    FROM delivery_bundle_commits_v2
                    WHERE run_id = :run_id AND idempotency_key = :idempotency_key
                    """
                ),
                {"run_id": run_id, "idempotency_key": idempotency_key},
            )
            existing = existing_result.mappings().first()
            if existing:
                if existing["request_digest"] != digest:
                    raise BundleIdempotencyMismatch(
                        "idempotency key was used for another commit"
                    )
                replay = await self._get_bundle_in_session(
                    session, str(existing["result_bundle_id"])
                )
                if replay is None:
                    raise RuntimeError("idempotency record references a missing bundle")
                return BundleCommitResult(bundle=replay, idempotent_replay=True)

            head_result = await session.execute(
                text(
                    "SELECT * FROM delivery_bundle_heads_v2 WHERE run_id = :run_id FOR UPDATE"
                ),
                {"run_id": run_id},
            )
            head_row = head_result.mappings().first()
            current = _vector_from_row(dict(head_row)) if head_row else None
            if current != expected:
                raise BundleRevisionConflict(current)
            await session.execute(
                text(
                    """
                    INSERT INTO delivery_bundle_commits_v2
                        (run_id, idempotency_key, request_digest, commit_kind,
                         base_bundle_id, result_bundle_id,
                         inverse_patch, metadata, created_at)
                    VALUES
                        (:run_id, :idempotency_key, :request_digest, :commit_kind,
                         :base_bundle_id, :result_bundle_id,
                         NULL, CAST(:metadata AS jsonb), NOW())
                    """
                ),
                {
                    "run_id": run_id,
                    "idempotency_key": idempotency_key,
                    "request_digest": digest,
                    "commit_kind": kind.value,
                    "base_bundle_id": expected.bundle_id,
                    "result_bundle_id": expected.bundle_id,
                    "metadata": _json_dumps(metadata),
                },
            )
            self._inject(PersistBoundary.IDEMPOTENCY_RECORD)
            current_bundle = await self._get_bundle_in_session(session, expected.bundle_id)
            if current_bundle is None:
                raise RuntimeError("current Bundle disappeared while recording receipt")
            return BundleCommitResult(bundle=current_bundle)

    async def commit(
        self,
        *,
        bundle: DeliveryBundle,
        kind: BundleCommitKind,
        idempotency_key: str,
        expected: Optional[BundleRevisionVector] = None,
        inverse_patch: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_request: Optional[Dict[str, Any]] = None,
        session: Any | None = None,
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
            inverse_patch=inverse_patch,
            metadata=metadata,
            idempotency_request=idempotency_request,
        )
        async with _session_scope(session) as session:
            # 缺少 head 行时无法用 SELECT ... FOR UPDATE 保护。事务级 advisory
            # lock 将同一个 run 的 create 与后续提交串行化，且不阻塞其他行程。
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:run_id, 0))"),
                {"run_id": run_id},
            )
            existing_result = await session.execute(
                text(
                    """
                    SELECT request_digest, result_bundle_id
                    FROM delivery_bundle_commits_v2
                    WHERE run_id = :run_id AND idempotency_key = :idempotency_key
                    """
                ),
                {"run_id": run_id, "idempotency_key": idempotency_key},
            )
            existing = existing_result.mappings().first()
            if existing:
                if existing["request_digest"] != digest:
                    raise BundleIdempotencyMismatch("idempotency key was used for another commit")
                replay = await self._get_bundle_in_session(session, str(existing["result_bundle_id"]))
                if replay is None:
                    raise RuntimeError("idempotency record references a missing bundle")
                return BundleCommitResult(bundle=replay, idempotent_replay=True)

            head_result = await session.execute(
                text("SELECT * FROM delivery_bundle_heads_v2 WHERE run_id = :run_id FOR UPDATE"),
                {"run_id": run_id},
            )
            head_row = head_result.mappings().first()
            current = _vector_from_row(dict(head_row)) if head_row else None
            if kind == BundleCommitKind.CREATE:
                if current is not None:
                    raise BundleRevisionConflict(current)
            elif current != expected:
                raise BundleRevisionConflict(current)

            await self._insert_snapshot(
                session=session,
                table="trip_workspace_v2_revisions",
                revision_column="workspace_revision",
                run_id=run_id,
                revision=bundle.manifest.workspace_revision,
                content_hash=bundle.manifest.content_hashes["workspace"],
                snapshot=bundle.workspace.model_dump(mode="json"),
            )
            self._inject(PersistBoundary.WORKSPACE_SNAPSHOT)
            await self._insert_snapshot(
                session=session,
                table="fact_store_v2_revisions",
                revision_column="fact_data_revision",
                run_id=run_id,
                revision=bundle.manifest.fact_data_revision,
                content_hash=bundle.manifest.content_hashes["fact_snapshot"],
                snapshot=bundle.fact_snapshot.model_dump(mode="json"),
            )
            self._inject(PersistBoundary.FACT_SNAPSHOT)
            await self._insert_snapshot(
                session=session,
                table="weather_context_v2_revisions",
                revision_column="weather_data_revision",
                run_id=run_id,
                revision=bundle.manifest.weather_data_revision,
                content_hash=bundle.manifest.content_hashes["weather_snapshot"],
                snapshot=bundle.weather_snapshot.model_dump(mode="json"),
            )
            self._inject(PersistBoundary.WEATHER_SNAPSHOT)

            await session.execute(
                text(
                    """
                    INSERT INTO delivery_bundles_v2
                        (bundle_id, run_id, workspace_revision, fact_data_revision,
                         weather_data_revision, manifest, bundle, created_at)
                    VALUES
                        (:bundle_id, :run_id, :workspace_revision, :fact_data_revision,
                         :weather_data_revision, CAST(:manifest AS jsonb),
                         CAST(:bundle AS jsonb), :created_at)
                    """
                ),
                {
                    "bundle_id": bundle.manifest.bundle_id,
                    "run_id": run_id,
                    "workspace_revision": bundle.manifest.workspace_revision,
                    "fact_data_revision": bundle.manifest.fact_data_revision,
                    "weather_data_revision": bundle.manifest.weather_data_revision,
                    "manifest": _json_dumps(bundle.manifest.model_dump(mode="json")),
                    "bundle": _json_dumps(bundle.model_dump(mode="json")),
                    "created_at": bundle.manifest.created_at,
                },
            )
            self._inject(PersistBoundary.BUNDLE)

            if current is None:
                await session.execute(
                    text(
                        """
                        INSERT INTO delivery_bundle_heads_v2
                            (run_id, current_bundle_id, workspace_revision,
                             fact_data_revision, weather_data_revision, updated_at)
                        VALUES
                            (:run_id, :bundle_id, :workspace_revision,
                             :fact_data_revision, :weather_data_revision, NOW())
                        """
                    ),
                    self._head_params(bundle),
                )
            else:
                update_result = await session.execute(
                    text(
                        """
                        UPDATE delivery_bundle_heads_v2
                        SET current_bundle_id = :bundle_id,
                            workspace_revision = :workspace_revision,
                            fact_data_revision = :fact_data_revision,
                            weather_data_revision = :weather_data_revision,
                            updated_at = NOW()
                        WHERE run_id = :run_id AND current_bundle_id = :expected_bundle_id
                        """
                    ),
                    {**self._head_params(bundle), "expected_bundle_id": current.bundle_id},
                )
                if update_result.rowcount != 1:
                    raise BundleRevisionConflict(current)
            self._inject(PersistBoundary.CURRENT_POINTER)

            await session.execute(
                text(
                    """
                    INSERT INTO delivery_bundle_commits_v2
                        (run_id, idempotency_key, request_digest, commit_kind,
                         base_bundle_id, result_bundle_id,
                         inverse_patch, metadata, created_at)
                    VALUES
                        (:run_id, :idempotency_key, :request_digest, :commit_kind,
                         :base_bundle_id, :result_bundle_id,
                         CAST(:inverse_patch AS jsonb), CAST(:metadata AS jsonb), NOW())
                    """
                ),
                {
                    "run_id": run_id,
                    "idempotency_key": idempotency_key,
                    "request_digest": digest,
                    "commit_kind": kind.value,
                    "base_bundle_id": expected.bundle_id if expected else None,
                    "result_bundle_id": bundle.manifest.bundle_id,
                    "inverse_patch": _json_dumps(inverse_patch),
                    "metadata": _json_dumps(metadata),
                },
            )
            self._inject(PersistBoundary.IDEMPOTENCY_RECORD)
            return BundleCommitResult(bundle=bundle)

    async def _get_bundle_in_session(self, session: Any, bundle_id: str) -> Optional[DeliveryBundle]:
        result = await session.execute(
            text(
                """
                SELECT run_id, manifest->>'contract_version' AS contract_stamp, bundle
                FROM delivery_bundles_v2
                WHERE bundle_id = :bundle_id
                """
            ),
            {"bundle_id": bundle_id},
        )
        row = result.mappings().first()
        if row is None or row["bundle"] is None:
            return None
        return self.bundle_from_row(
            run_id=str(row["run_id"]),
            contract_stamp=row["contract_stamp"],
            payload=_json_loads(row["bundle"]),
        )

    # 标识符白名单：不把用户输入拼进 SQL 标识符。
    _SNAPSHOT_TABLE_COLUMNS: Dict[str, str] = {
        "trip_workspace_v2_revisions": "workspace_revision",
        "fact_store_v2_revisions": "fact_data_revision",
        "weather_context_v2_revisions": "weather_data_revision",
    }

    async def _insert_snapshot(
        self,
        *,
        session: Any,
        table: str,
        revision_column: str,
        run_id: str,
        revision: int,
        content_hash: str,
        snapshot: Dict[str, Any],
    ) -> None:
        allowed_column = self._SNAPSHOT_TABLE_COLUMNS.get(table)
        if allowed_column is None or allowed_column != revision_column:
            raise ValueError(
                f"refusing SQL identifier assemble for table={table!r} "
                f"column={revision_column!r} (not in snapshot whitelist)"
            )
        await session.execute(
            text(
                f"""
                INSERT INTO {table} (run_id, {revision_column}, content_hash, snapshot, created_at)
                VALUES (:run_id, :revision, :content_hash, CAST(:snapshot AS jsonb), NOW())
                ON CONFLICT (run_id, {revision_column}) DO NOTHING
                """
            ),
            {
                "run_id": run_id,
                "revision": revision,
                "content_hash": content_hash,
                "snapshot": _json_dumps(snapshot),
            },
        )
        result = await session.execute(
            text(
                f"""
                SELECT content_hash FROM {table}
                WHERE run_id = :run_id AND {revision_column} = :revision
                """
            ),
            {"run_id": run_id, "revision": revision},
        )
        persisted_hash = result.scalar_one()
        if persisted_hash != content_hash:
            raise BundleRevisionReuse(
                f"{table} revision {revision} already contains different content"
            )

    @staticmethod
    def _head_params(bundle: DeliveryBundle) -> Dict[str, Any]:
        manifest = bundle.manifest
        return {
            "run_id": manifest.run_id,
            "bundle_id": manifest.bundle_id,
            "workspace_revision": manifest.workspace_revision,
            "fact_data_revision": manifest.fact_data_revision,
            "weather_data_revision": manifest.weather_data_revision,
        }


class InMemoryDeliveryBundleStore(DeliveryBundleStore):
    """事务语义与 SQL 实现一致的内存参考实现，供 reducer/store 测试使用。"""

    def __init__(self, *, failure_injector: Optional[FailureInjector] = None) -> None:
        super().__init__(failure_injector=failure_injector)
        self._bundles: Dict[str, DeliveryBundle] = {}
        self._heads: Dict[str, str] = {}
        self._commits: Dict[
            tuple[str, str],
            tuple[str, str, Optional[Dict[str, Any]], Dict[str, Any], BundleCommitKind],
        ] = {}
        self._workspace_revisions: Dict[tuple[str, int], str] = {}
        self._fact_revisions: Dict[tuple[str, int], str] = {}
        self._weather_revisions: Dict[tuple[str, int], str] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def snapshot_for_initial_delivery(self) -> tuple[
        Dict[str, DeliveryBundle],
        Dict[str, str],
        Dict[tuple[str, str], tuple[str, str, Optional[Dict[str, Any]], Dict[str, Any], BundleCommitKind]],
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
            Dict[tuple[str, str], tuple[str, str, Optional[Dict[str, Any]], Dict[str, Any], BundleCommitKind]],
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
        _, bundle_id, inverse_patch, metadata, _ = existing
        return BundleCommitRecord(
            result=BundleCommitResult(bundle=self._bundles[bundle_id], idempotent_replay=True),
            inverse_patch=inverse_patch,
            metadata=metadata,
        )

    async def get_undo_head(self, run_id: str) -> Optional[BundleUndoHead]:
        current = await self.get_current(run_id)
        if current is None:
            return None
        matches: list[BundleUndoHead] = []
        for (commit_run_id, mutation_id), (
            _,
            bundle_id,
            inverse,
            metadata,
            kind,
        ) in self._commits.items():
            bundle = self._bundles[bundle_id]
            if (
                commit_run_id != run_id
                or inverse is None
                or kind not in {
                    BundleCommitKind.WORKSPACE_MUTATION,
                    BundleCommitKind.UNDO,
                }
                or bundle.manifest.workspace_revision > current.manifest.workspace_revision
            ):
                continue
            matches.append(
                BundleUndoHead(
                    mutation_id=mutation_id,
                    label=str(
                        metadata.get("undo_label")
                        or f"撤销：{metadata.get('label') or '上一步调整'}"
                    ),
                    semantic_label=str(
                        metadata.get("semantic_label")
                        or metadata.get("label")
                        or "上一步调整"
                    ),
                    inverse_patch=inverse,
                    result_bundle_id=bundle_id,
                    workspace_revision=bundle.manifest.workspace_revision,
                )
            )
        if not matches:
            return None
        return max(
            matches,
            key=lambda item: (
                self._bundles[item.result_bundle_id].manifest.created_at,
                item.result_bundle_id,
            ),
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
        if kind not in {
            BundleCommitKind.WORKSPACE_MUTATION_RECEIPT,
            BundleCommitKind.WEATHER_REFRESH_RECEIPT,
        }:
            raise ValueError("unsupported no-op receipt kind")
        metadata = metadata or {}
        digest = _request_digest(
            bundle=None,
            kind=kind,
            expected=expected,
            inverse_patch=None,
            metadata=metadata,
            idempotency_request=idempotency_request,
        )
        lock = self._locks.setdefault(run_id, asyncio.Lock())
        async with lock:
            commit_key = (run_id, idempotency_key)
            existing = self._commits.get(commit_key)
            if existing:
                existing_digest, bundle_id, _, _, _ = existing
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
                    None,
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
        inverse_patch: Optional[Dict[str, Any]] = None,
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
            inverse_patch=inverse_patch,
            metadata=metadata,
            idempotency_request=idempotency_request,
        )
        lock = self._locks.setdefault(run_id, asyncio.Lock())
        async with lock:
            commit_key = (run_id, idempotency_key)
            existing = self._commits.get(commit_key)
            if existing:
                existing_digest, bundle_id, _, _, _ = existing
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
                inverse_patch,
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
