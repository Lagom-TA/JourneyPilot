"""租约被接管时，旧执行者与恢复扫描不能覆盖新执行者。"""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from travel_agent.runtime.background_jobs import BackgroundJobWorker
from travel_agent.runtime.cancellation import RunCancelled
from travel_agent.runtime.job_contracts import BackgroundJob, BackgroundJobType
from travel_agent.runtime.run_contracts import TripRunStatus
from travel_agent.runtime.run_recovery import RunRecoveryService
from travel_agent.storage.run_execution_store import RunRecoveryCandidate
from travel_agent.storage.trip_run_store import TripRunStore


async def test_recovery_rolls_back_if_a_lease_is_claimed_during_probe(monkeypatch):
    from travel_agent.runtime import run_recovery

    state = SimpleNamespace(status=TripRunStatus.RUNNING, live=False, events=[])
    candidate = RunRecoveryCandidate(
        run_id="run", status=TripRunStatus.RUNNING, mode="deep",
        resume_policy="checkpoint", current_node="research", execution=None,
    )

    @asynccontextmanager
    async def transaction():
        status, events = state.status, list(state.events)
        try:
            yield object()
        except Exception:
            state.status, state.events = status, events
            raise

    class Runs:
        async def transition_status(self, _run_id, status, **kwargs):
            assert kwargs["db_session"] is not None
            state.status = status
            state.events.append(kwargs["event_type"])

    class Executions:
        async def list_recovery_candidates(self):
            return [candidate]

        async def record_recovery(self, _run_id, **kwargs):
            assert kwargs["db_session"] is not None
            return None if state.live else object()

    async def probe(_run_id):
        state.live = True
        return True

    monkeypatch.setattr(run_recovery, "get_db_session", transaction)
    service = RunRecoveryService(
        trip_run_store=Runs(), execution_store=Executions(), checkpoint_probe=probe,
    )
    report = await service.sweep()
    assert not report.outcomes and not report.failures
    assert state.status is TripRunStatus.RUNNING and state.events == []


async def test_old_job_handler_cannot_finish_after_a_new_claim():
    started, finish = asyncio.Event(), asyncio.Event()

    class Store:
        owner = "claim-1"
        result = None
        attempts = []

        async def complete(self, _job_id, *, lease_owner, result):
            self.attempts.append(lease_owner)
            if lease_owner != self.owner:
                return False
            self.result = result
            return True

    async def handler(_job):
        started.set()
        await finish.wait()
        return {"old": True}

    store = Store()
    worker = BackgroundJobWorker(store, {BackgroundJobType.MEMORY_EXTRACTION: handler})
    job = BackgroundJob(
        job_id="job", job_type=BackgroundJobType.MEMORY_EXTRACTION,
        dedupe_key="turn", lease_owner="claim-1",
    )
    task = asyncio.create_task(worker._execute(job))
    await started.wait()
    store.owner = "claim-2"
    finish.set()
    await task
    assert store.attempts == ["claim-1"] and store.result is None


async def test_status_transition_rejects_a_lost_execution_lease():
    class Result:
        def __init__(self, value):
            self.value = value

        def mappings(self):
            return self

        def first(self):
            return self.value

    class Session:
        def __init__(self):
            self.calls = []

        async def execute(self, statement, params):
            self.calls.append((str(statement), params))
            return Result({"status": "running"} if len(self.calls) == 1 else None)

    session = Session()
    with pytest.raises(RunCancelled) as exc:
        await TripRunStore().transition_status(
            "run", TripRunStatus.COMPLETED, db_session=session,
            execution_lease_token="old-lease",
        )
    assert exc.value.reason == "lease_lost"
    assert len(session.calls) == 3
    assert "FOR UPDATE" in session.calls[1][0]
    assert "clock_timestamp()" in session.calls[2][0]
    assert session.calls[2][1]["lease_token"] == "old-lease"
