"""租约在取得行锁后重新判断，避免锁等待跨过有效期。"""

from types import SimpleNamespace

import pytest

from travel_agent.runtime.cancellation import RunCancelled
from travel_agent.storage.trip_run_store import _require_execution_lease
from travel_agent.storage.worker_journal_store import JournalConflict, WorkerJournalStore


class _Session:
    def __init__(self):
        self.statements = []

    async def execute(self, statement, parameters):
        self.statements.append(str(statement))
        # 模拟租约在等待行锁期间过期。
        return SimpleNamespace(first=lambda: None if "clock_timestamp()" in str(statement) else ("run",))


async def test_terminal_write_rechecks_expiry_after_execution_lock():
    session = _Session()
    with pytest.raises(RunCancelled):
        await _require_execution_lease(session, "run", "lease")
    assert "FOR UPDATE" in session.statements[0]
    assert "clock_timestamp()" in session.statements[1]


async def test_journal_locks_parent_before_rechecking_execution_lease():
    session = _Session()
    await WorkerJournalStore._lock_run(session, "run")
    with pytest.raises(JournalConflict):
        await WorkerJournalStore._require_lease(session, "run", "lease")
    assert "trip_runs" in session.statements[0] and "FOR KEY SHARE" in session.statements[0]
    assert "trip_run_executions" in session.statements[1] and "FOR UPDATE" in session.statements[1]
    assert "clock_timestamp()" in session.statements[2]
