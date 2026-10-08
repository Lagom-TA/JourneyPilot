"""Worker snapshots are recovery aids; gates and delivery stores own admission.

Use the same typed serializer as LangGraph. Writes are version-CAS and fenced
by the live execution lease, in one business database transaction. A graph
checkpoint and this transaction are deliberately not treated as one commit.
"""
from copy import deepcopy
from functools import wraps

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from sqlalchemy import text

from .database import get_db_session


class JournalConflict(RuntimeError):
    pass


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
            # Row lock also orders this commit against lease takeover/release.
            lease = await session.execute(text(
                "SELECT run_id FROM trip_run_executions WHERE run_id=:run_id "
                "AND lease_token=:lease_token AND lease_expires_at>NOW() FOR UPDATE"
            ), {"run_id": run_id, "lease_token": lease_token})
            if lease.first() is None:
                raise JournalConflict("worker journal execution lease lost")
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


class InMemoryWorkerJournalStore:
    """Fault injection adapter; production never falls back to this store."""
    def __init__(self):
        self.rows = {}

    async def load(self, run_id, scope_id):
        return deepcopy(self.rows.get((run_id, scope_id), (0, {})))

    async def save(self, run_id, scope_id, version, payload, *, lease_token=None):
        key = run_id, scope_id
        if self.rows.get(key, (0, {}))[0] != version:
            raise JournalConflict("concurrent worker journal write")
        self.rows[key] = version + 1, deepcopy(payload)
        return version + 1
