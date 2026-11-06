"""在配置的数据库中用临时表验证运行事务；外层事务始终回滚。"""

from contextlib import asynccontextmanager
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from travel_agent.storage import database

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(os.getenv("JP_RUNTIME_ROLLBACK_TESTS") != "1", reason="需要显式启用配置库的临时表验证"),
]


@pytest.fixture
async def rollback_database(monkeypatch):
    from travel_agent.memory import chat_session
    from travel_agent.planning.delivery import persistence
    from travel_agent.runtime import run_recovery
    from travel_agent.storage import (
        background_job_store, delivery_bundle_store, run_command_store,
        run_execution_store, trip_run_store, worker_journal_store,
    )

    tables = (
        "chat_sessions", "chat_session_events", "trip_runs", "trip_run_states",
        "trip_run_events", "trip_run_executions", "trip_run_commands",
        "run_worker_journals", "background_jobs", "delivery_bundles",
        "delivery_bundle_heads", "delivery_bundle_commits", "trip_workspace_revisions",
        "fact_store_revisions", "weather_context_revisions",
    )
    engine = database.get_engine()
    async with engine.connect() as connection:
        outer = await connection.begin()
        try:
            for name in tables:
                await connection.execute(text(
                    f"CREATE TEMP TABLE {name} (LIKE public.{name} INCLUDING ALL) ON COMMIT DROP"
                ))
            for name in ("chat_session_events", "trip_run_events"):
                await connection.execute(text(f"CREATE TEMP SEQUENCE {name}_runtime_sequence"))
                await connection.execute(text(
                    f"ALTER TABLE {name} ALTER COLUMN event_id "
                    f"SET DEFAULT nextval('pg_temp.{name}_runtime_sequence')"
                ))
            await connection.execute(text("SET LOCAL search_path = pg_temp"))
            session = AsyncSession(bind=connection, expire_on_commit=False)

            @asynccontextmanager
            async def nested_session():
                async with session.begin_nested():
                    yield session

            for module in (
                chat_session, persistence, run_recovery, background_job_store,
                delivery_bundle_store, run_command_store, run_execution_store, trip_run_store,
                worker_journal_store,
            ):
                monkeypatch.setattr(module, "get_db_session", nested_session)
            try:
                yield session
            finally:
                await session.close()
        finally:
            await outer.rollback()
    await database.close_db()


async def test_long_turn_pages_without_repeating(rollback_database, monkeypatch):
    from travel_agent.memory import chat_session

    monkeypatch.setattr(chat_session, "TURN_PAGE_MAX_EVENTS", 5)
    memory = chat_session.ChatSessionMemory()
    for index, steps in [(0, 0), (1, 6)]:
        await memory.save_turn(
            session_id="session-runtime", user_id="local", mode="fast",
            user_message=f"问题{index}", user_message_id=f"u{index}",
            assistant_message_id=f"a{index}", assistant_content="回答",
            assistant_display_content="回答", controlled_trip_identity=None,
            thinking_steps=[{"step_id": str(n), "content": "过程"} for n in range(steps)],
        )
    latest = await memory.list_turns("local", "session-runtime")
    older = await memory.list_turns("local", "session-runtime", before_turn=latest["next_before"])
    assert len(latest["turns"]) == len(older["turns"]) == 1
    assert latest["turns"][0]["turn_id"] != older["turns"][0]["turn_id"]
    assert not older["has_more"]


async def test_recovery_and_delivery_reject_a_replaced_lease(rollback_database):
    from tests.db.test_generation_delivery import _delivery_state
    from travel_agent.planning.delivery.assembly import assemble_delivery_bundle
    from travel_agent.planning.delivery.persistence import _commit_initial_delivery_atomically
    from travel_agent.runtime.cancellation import RunCancelled
    from travel_agent.runtime.journal import current_execution_lease
    from travel_agent.runtime.run_contracts import TripRunStatus
    from travel_agent.runtime.run_recovery import RunRecoveryService
    from travel_agent.storage.delivery_bundle_store import DeliveryBundleStore
    from travel_agent.storage.run_execution_store import RunExecutionStore
    from travel_agent.storage.trip_run_store import TripRunStore

    runs, executions, bundles = TripRunStore(), RunExecutionStore(), DeliveryBundleStore()
    run = await runs.create_run(session_id="session-runtime", user_id="local", mode="deep", resume_policy="checkpoint")
    await runs.transition_status(run.run_id, TripRunStatus.RUNNING)
    old = await executions.claim(run.run_id, lease_seconds=45)
    await rollback_database.execute(text(
        "UPDATE trip_run_executions SET lease_expires_at = NOW() - INTERVAL '1 second' WHERE run_id = :run_id"
    ), {"run_id": run.run_id})
    assert not await executions.heartbeat(run.run_id, lease_token=old.lease_token, lease_seconds=45)
    replacement = None

    async def probe(_run_id):
        nonlocal replacement
        replacement = await executions.claim(run.run_id, lease_seconds=45)
        return True

    report = await RunRecoveryService(
        trip_run_store=runs, execution_store=executions, checkpoint_probe=probe,
    ).sweep()
    assert not report.outcomes and not report.failures
    assert (await runs.get_run(run.run_id)).status is TripRunStatus.RUNNING
    assert (await executions.get(run.run_id)).lease_token == replacement.lease_token
    with pytest.raises(RunCancelled):
        await runs.transition_status(run.run_id, TripRunStatus.FAILED, execution_lease_token=old.lease_token)

    state = _delivery_state(run.run_id)
    token = current_execution_lease.set(old.lease_token)
    try:
        with pytest.raises(RunCancelled):
            await _commit_initial_delivery_atomically(
                bundle_store=bundles, trip_store=runs, state=state,
                bundle=assemble_delivery_bundle(state),
            )
    finally:
        current_execution_lease.reset(token)
    assert await bundles.get_current(run.run_id) is None
    assert (await runs.get_run(run.run_id)).status is TripRunStatus.RUNNING


async def test_reclaimed_job_rejects_old_owner(rollback_database):
    from travel_agent.runtime.job_contracts import BackgroundJobStatus, BackgroundJobType
    from travel_agent.storage.background_job_store import BackgroundJobStore

    store = BackgroundJobStore()
    await store.enqueue(BackgroundJobType.MEMORY_EXTRACTION, "runtime-turn", {}, max_attempts=2)
    (old,) = await store.claim(lease_seconds=45)
    await rollback_database.execute(text(
        "UPDATE background_jobs SET lease_expires_at = NOW() - INTERVAL '1 second' WHERE job_id = :job_id"
    ), {"job_id": old.job_id})
    (replacement,) = await store.claim(lease_seconds=45)
    assert replacement.lease_owner != old.lease_owner
    assert not await store.complete(old.job_id, lease_owner=old.lease_owner, result={"old": True})
    assert await store.complete(replacement.job_id, lease_owner=replacement.lease_owner, result={"current": True})
    assert (await store.get(old.job_id)).status is BackgroundJobStatus.COMPLETED

    await store.enqueue(BackgroundJobType.MEMORY_EXTRACTION, "runtime-last-attempt", {}, max_attempts=1)
    (last,) = await store.claim(lease_seconds=45)
    await rollback_database.execute(text(
        "UPDATE background_jobs SET lease_expires_at = NOW() - INTERVAL '1 second' WHERE job_id = :job_id"
    ), {"job_id": last.job_id})
    assert await store.claim(lease_seconds=45) == []
    assert (await store.get(last.job_id)).status is BackgroundJobStatus.DEAD


async def test_expired_leases_are_rejected_inside_a_long_transaction(rollback_database):
    from travel_agent.runtime.cancellation import RunCancelled
    from travel_agent.runtime.job_contracts import BackgroundJobType
    from travel_agent.runtime.run_contracts import TripRunStatus
    from travel_agent.storage.background_job_store import BackgroundJobStore
    from travel_agent.storage.run_execution_store import RunExecutionStore
    from travel_agent.storage.trip_run_store import TripRunStore
    from travel_agent.storage.worker_journal_store import JournalConflict, WorkerJournalStore

    runs, executions, jobs = TripRunStore(), RunExecutionStore(), BackgroundJobStore()
    run = await runs.create_run(session_id="lease-clock", user_id="local", mode="fast")
    await runs.transition_status(run.run_id, TripRunStatus.RUNNING)
    lease = await executions.claim(run.run_id, lease_seconds=60)
    job, _ = await jobs.enqueue(BackgroundJobType.MEMORY_EXTRACTION, "lease-clock", {})
    (job,) = await jobs.claim(lease_seconds=60)
    await rollback_database.execute(text(
        "UPDATE trip_run_executions SET lease_expires_at = NOW() + INTERVAL '10 milliseconds' WHERE run_id = :run_id"
    ), {"run_id": run.run_id})
    await rollback_database.execute(text(
        "UPDATE background_jobs SET lease_expires_at = NOW() + INTERVAL '10 milliseconds' WHERE job_id = :job_id"
    ), {"job_id": job.job_id})
    await rollback_database.execute(text("SELECT pg_sleep(0.05)"))

    assert not await executions.heartbeat(run.run_id, lease_token=lease.lease_token, lease_seconds=60)
    with pytest.raises(RunCancelled):
        await runs.transition_status(run.run_id, TripRunStatus.FAILED, execution_lease_token=lease.lease_token)

    with pytest.raises(JournalConflict):
        await WorkerJournalStore().save(run.run_id, "scope", 0, {}, lease_token=lease.lease_token)
    assert not await jobs.renew_lease(job.job_id, lease_owner=job.lease_owner, lease_seconds=60)
    assert not await jobs.complete(job.job_id, lease_owner=job.lease_owner, result={})


async def test_orphan_recovery_settles_status_lease_and_command(rollback_database):
    from travel_agent.runtime.command_contracts import RunCommandStatus, RunCommandType
    from travel_agent.runtime.run_contracts import RunRecoveryStatus, TripRunStatus
    from travel_agent.runtime.run_recovery import RunRecoveryService
    from travel_agent.storage.run_command_store import RunCommandStore
    from travel_agent.storage.run_execution_store import RunExecutionStore
    from travel_agent.storage.trip_run_store import TripRunStore

    runs, executions, commands = TripRunStore(), RunExecutionStore(), RunCommandStore()
    run = await runs.create_run(session_id="session-runtime", user_id="local", mode="deep", resume_policy="checkpoint")
    await runs.transition_status(run.run_id, TripRunStatus.RUNNING)
    await executions.claim(run.run_id, lease_seconds=45)
    command, _ = await commands.enqueue(run.run_id, RunCommandType.CANCEL, {})
    await rollback_database.execute(text(
        "UPDATE trip_run_executions SET lease_expires_at = NOW() - INTERVAL '1 second' WHERE run_id = :run_id"
    ), {"run_id": run.run_id})

    async def probe(_run_id):
        return True

    report = await RunRecoveryService(
        trip_run_store=runs, execution_store=executions, command_store=commands, checkpoint_probe=probe,
    ).sweep()
    assert len(report.outcomes) == 1 and not report.failures
    assert (await runs.get_run(run.run_id)).status is TripRunStatus.INTERRUPTED
    assert (await executions.get(run.run_id)).recovery_status is RunRecoveryStatus.RESUME_AVAILABLE
    assert (await commands.get(run.run_id, command.command_id)).status is RunCommandStatus.REJECTED


async def test_waiting_run_keeps_its_pending_command(rollback_database):
    from travel_agent.runtime.command_contracts import RunCommandStatus, RunCommandType
    from travel_agent.runtime.run_contracts import TripRunStatus
    from travel_agent.runtime.run_recovery import RunRecoveryService
    from travel_agent.storage.run_command_store import RunCommandStore
    from travel_agent.storage.run_execution_store import RunExecutionStore
    from travel_agent.storage.trip_run_store import TripRunStore

    runs, executions, commands = TripRunStore(), RunExecutionStore(), RunCommandStore()
    run = await runs.create_run(session_id="session-runtime", user_id="local", mode="deep")
    await runs.transition_status(run.run_id, TripRunStatus.RUNNING)
    await runs.transition_status(run.run_id, TripRunStatus.AWAITING_INPUT)
    await executions.claim(run.run_id, lease_seconds=45)
    command, _ = await commands.enqueue(run.run_id, RunCommandType.SUPPLEMENT, {"content": "留待继续"})
    await rollback_database.execute(text(
        "UPDATE trip_run_executions SET lease_expires_at = NOW() - INTERVAL '1 second' WHERE run_id = :run_id"
    ), {"run_id": run.run_id})

    report = await RunRecoveryService(
        trip_run_store=runs, execution_store=executions, command_store=commands,
    ).sweep()
    assert len(report.outcomes) == 1 and not report.failures
    assert (await runs.get_run(run.run_id)).status is TripRunStatus.AWAITING_INPUT
    assert (await executions.get(run.run_id)).lease_token is None
    assert (await commands.get(run.run_id, command.command_id)).status is RunCommandStatus.PENDING
