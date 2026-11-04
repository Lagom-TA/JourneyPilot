"""worker 快照是规划图的恢复辅助数据。

使用与 LangGraph 相同的类型化序列化器。写入按 version 做 CAS，并受活跃执行
租约约束，全部在一个业务数据库事务内完成。图 checkpoint 与该事务不视为同一次
提交。
"""
from functools import wraps

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from sqlalchemy import text

from .database import get_db_session


class JournalConflict(RuntimeError):
    pass


TOOL_BUDGET_SCOPE = "__tool_budget__"


def initial_tool_budget() -> tuple[str, bytes]:
    return JsonPlusSerializer().dumps_typed({"calls": 0, "retries": {}})


def journal_boundary(method):
    @wraps(method)
    async def wrapped(*args, **kwargs):
        try:
            return await method(*args, **kwargs)
        except JournalConflict:
            raise
        except Exception as exc:
            raise JournalConflict("worker journal persistence unavailable") from exc
    return wrapped


class WorkerJournalStore:
    async def create_initial_tool_budget(self, run_id, *, db_session):
        kind, payload = initial_tool_budget()
        await db_session.execute(text(
            "INSERT INTO run_worker_journals "
            "(run_id, scope_id, version, payload_type, payload) "
            "VALUES (:run_id, :scope_id, 1, :kind, :payload)"
        ), {"run_id": run_id, "scope_id": TOOL_BUDGET_SCOPE, "kind": kind, "payload": payload})

    @staticmethod
    async def _lock_run(session, run_id):
        # 插入 journal 时外键会读取 trip_runs；先拿父行锁，避免与终态更新的锁顺序相反。
        result = await session.execute(text(
            "SELECT run_id FROM trip_runs WHERE run_id=:run_id FOR KEY SHARE"
        ), {"run_id": run_id})
        if result.first() is None:
            raise JournalConflict("worker journal run not found")

    @staticmethod
    async def _require_lease(session, run_id, lease_token):
        await session.execute(text(
            "SELECT run_id FROM trip_run_executions WHERE run_id=:run_id FOR UPDATE"
        ), {"run_id": run_id})
        lease = await session.execute(text(
            "SELECT run_id FROM trip_run_executions WHERE run_id=:run_id "
            "AND lease_token=:lease_token AND lease_expires_at>clock_timestamp()"
        ), {"run_id": run_id, "lease_token": lease_token})
        if lease.first() is None:
            raise JournalConflict("worker journal execution lease lost")

    @journal_boundary
    async def reserve_tool(self, run_id, tool_name, *, lease_token, limit, retry=False):
        async with get_db_session() as session:
            await self._lock_run(session, run_id)
            await self._require_lease(session, run_id, lease_token)
            result = await session.execute(text(
                "SELECT version, payload_type, payload FROM run_worker_journals "
                "WHERE run_id=:run_id AND scope_id=:scope_id FOR UPDATE"
            ), {"run_id": run_id, "scope_id": TOOL_BUDGET_SCOPE})
            row = result.mappings().first()
            if row is None:
                raise JournalConflict("工具预算记录不存在，不能安全恢复")
            payload = JsonPlusSerializer().loads_typed((row["payload_type"], bytes(row["payload"])))
            calls = int(payload.get("calls") or 0)
            if limit is not None and calls >= limit:
                return None
            retries = dict(payload.get("retries") or {})
            if retry:
                retries[tool_name] = int(retries.get(tool_name) or 0) + 1
            payload = {"calls": calls + 1, "retries": retries}
            kind, data = JsonPlusSerializer().dumps_typed(payload)
            await session.execute(text(
                "UPDATE run_worker_journals SET version=version+1, payload_type=:kind, "
                "payload=:data, updated_at=NOW() WHERE run_id=:run_id AND scope_id=:scope_id"
            ), {"run_id": run_id, "scope_id": TOOL_BUDGET_SCOPE, "kind": kind, "data": data})
            return payload

    @journal_boundary
    async def load(self, run_id, scope_id):
        async with get_db_session() as session:
            result = await session.execute(text(
                "SELECT version, payload_type, payload FROM run_worker_journals "
                "WHERE run_id=:run_id AND scope_id=:scope_id"
            ), {"run_id": run_id, "scope_id": scope_id})
            row = result.mappings().first()
        if row is None:
            return 0, {}
        return row["version"], JsonPlusSerializer().loads_typed(
            (row["payload_type"], bytes(row["payload"]))
        )

    @journal_boundary
    async def save(self, run_id, scope_id, version, payload, *, lease_token):
        kind, data = JsonPlusSerializer().dumps_typed(payload)
        async with get_db_session() as session:
            await self._lock_run(session, run_id)
            await self._require_lease(session, run_id, lease_token)
            result = await session.execute(text("""
                INSERT INTO run_worker_journals
                    (run_id, scope_id, version, payload_type, payload)
                SELECT :run_id, :scope_id, 1, :kind, :data WHERE :version=0
                ON CONFLICT (run_id, scope_id) DO NOTHING
                RETURNING version
            """), {"run_id": run_id, "scope_id": scope_id, "version": version,
                   "kind": kind, "data": data}) if version == 0 else await session.execute(text("""
                UPDATE run_worker_journals SET version=version+1,
                    payload_type=:kind, payload=:data, updated_at=NOW()
                WHERE run_id=:run_id AND scope_id=:scope_id AND version=:version
                RETURNING version
            """), {"run_id": run_id, "scope_id": scope_id, "version": version,
                   "kind": kind, "data": data})
            updated = result.scalar_one_or_none()
            if updated is None:
                raise JournalConflict("concurrent worker journal write")
        return updated

