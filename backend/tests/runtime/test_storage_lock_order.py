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


@pytest.mark.parametrize("operation", ["save", "reserve_tool"])
@pytest.mark.parametrize("expired_after_lock", [False, True], ids=["live", "expired-after-lock"])
async def test_journal_writes_lock_parent_and_recheck_lease_before_mutation(
    monkeypatch, operation, expired_after_lock,
):
    session = _Session(expired_after_lock=expired_after_lock)

    @asynccontextmanager
    async def transaction():
        yield session

    monkeypatch.setattr(worker_journal_store, "get_db_session", transaction)
    store = WorkerJournalStore()

    async def write():
        if operation == "save":
            return await store.save("run", "scope", 0, {"answer": "已完成"}, lease_token="lease")
        return await store.reserve_tool("run", "search", lease_token="lease", limit=2)

    if expired_after_lock:
        with pytest.raises(JournalConflict, match="execution lease lost"):
            await write()
        assert session.writes == []
    else:
        result = await write()
        assert result == (1 if operation == "save" else {"calls": 1, "retries": {}})
        assert len(session.writes) == 1

    guards = {
        name: [index for index, (sql, _) in enumerate(session.statements)
               if all(part in sql for part in parts)]
        for name, parts in {
            "parent": ("FROM trip_runs", "FOR KEY SHARE"),
            "execution": ("FROM trip_run_executions", "FOR UPDATE"),
            "lease": ("FROM trip_run_executions", "clock_timestamp()"),
        }.items()
    }
    assert all(guards.values()), "写入口必须执行父行锁、执行行锁与实时租约校验"
    assert guards["parent"][0] < guards["execution"][0] < guards["lease"][0]
    assert session.statements[guards["lease"][0]][1] == {"run_id": "run", "lease_token": "lease"}
    assert all(session.statements.index(write) > guards["lease"][0] for write in session.writes)
