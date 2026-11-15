"""租约在取得行锁后重新判断，避免锁等待跨过有效期。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from travel_agent.storage import worker_journal_store
from travel_agent.storage.worker_journal_store import (
    JournalConflict,
    WorkerJournalStore,
    initial_tool_budget,
)


class _Session:
    def __init__(self, *, expired_after_lock):
        self.expired_after_lock = expired_after_lock
        self.statements = []
        self.writes = []

    async def execute(self, statement, parameters):
        sql = " ".join(str(statement).split())
        self.statements.append((sql, parameters))
        if sql.startswith(("INSERT", "UPDATE")):
            self.writes.append((sql, parameters))
            return SimpleNamespace(scalar_one_or_none=lambda: 1)
        if "clock_timestamp()" in sql:
            # 模拟等待执行行锁期间失效，锁前的租约判断不能授权写入。
            return SimpleNamespace(first=lambda: None if self.expired_after_lock else ("run",))
        if "FROM run_worker_journals" in sql:
            kind, payload = initial_tool_budget()
            row = {"version": 1, "payload_type": kind, "payload": payload}
            return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: row))
        return SimpleNamespace(first=lambda: ("run",))


def _store_with_session(monkeypatch, *, expired_after_lock):
    session = _Session(expired_after_lock=expired_after_lock)

    @asynccontextmanager
    async def transaction():
        yield session

    monkeypatch.setattr(worker_journal_store, "get_db_session", transaction)
    return WorkerJournalStore(), session


def _assert_guard_order(session):
    def index_of(*parts):
        return next(
            (index for index, (sql, _) in enumerate(session.statements)
             if all(part in sql for part in parts)),
            None,
        )

    parent = index_of("FROM trip_runs", "FOR KEY SHARE")
    execution = index_of("FROM trip_run_executions", "FOR UPDATE")
    lease = index_of("FROM trip_run_executions", "clock_timestamp()")
    assert parent is not None and execution is not None and lease is not None
    assert parent < execution < lease
    assert session.statements[lease][1] == {"run_id": "run", "lease_token": "lease"}
    return lease


_OPERATIONS = [
    pytest.param("save", ("run", "scope", 0, {"answer": "已完成"}), {}, 1, id="save"),
    pytest.param(
        "reserve_tool", ("run", "search"), {"limit": 2}, {"calls": 1, "retries": {}},
        id="reserve_tool",
    ),
]


@pytest.mark.parametrize("operation,args,kwargs,expected", _OPERATIONS)
async def test_journal_writes_after_locking_and_checking_live_lease(
    monkeypatch, operation, args, kwargs, expected,
):
    store, session = _store_with_session(monkeypatch, expired_after_lock=False)

    result = await getattr(store, operation)(*args, lease_token="lease", **kwargs)

    assert result == expected
    assert len(session.writes) == 1
    lease_index = _assert_guard_order(session)
    assert session.statements.index(session.writes[0]) > lease_index


@pytest.mark.parametrize("operation,args,kwargs,expected", _OPERATIONS)
async def test_journal_rejects_lease_expired_during_lock_wait(
    monkeypatch, operation, args, kwargs, expected,
):
    store, session = _store_with_session(monkeypatch, expired_after_lock=True)

    with pytest.raises(JournalConflict, match="execution lease lost"):
        await getattr(store, operation)(*args, lease_token="lease", **kwargs)

    assert session.writes == []
    _assert_guard_order(session)
