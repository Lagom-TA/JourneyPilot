"""在当前配置库的临时表和回滚事务中验证记忆删除。"""

from contextlib import asynccontextmanager
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from travel_agent.storage import database

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(os.getenv("JP_B6_ROLLBACK_TESTS") != "1", reason="需要显式启用配置库的临时表验证"),
]


@pytest.fixture
async def memory_database(monkeypatch):
    from travel_agent.memory import memory_extractor, memory_store
    from travel_agent.storage import background_job_store, memory_lifecycle_store

    engine = database.get_engine()
    async with engine.connect() as connection:
        outer = await connection.begin()
        try:
            for name in (
                "background_jobs", "user_profiles", "memory_facts", "memory_entities",
                "memory_relations", "memory_forgetting_audits", "chat_sessions",
            ):
                await connection.execute(text(
                    f"CREATE TEMP TABLE {name} (LIKE public.{name} INCLUDING ALL) ON COMMIT DROP"
                ))
            for name, field in (("memory_facts", "fact_id"), ("memory_entities", "entity_id"), ("memory_relations", "relation_id")):
                await connection.execute(text(f"CREATE TEMP SEQUENCE {name}_b6_sequence"))
                await connection.execute(text(
                    f"ALTER TABLE {name} ALTER COLUMN {field} SET DEFAULT nextval('pg_temp.{name}_b6_sequence')"
                ))
            await connection.execute(text("SET LOCAL search_path = pg_temp, public"))
            session = AsyncSession(bind=connection, expire_on_commit=False)

            @asynccontextmanager
            async def nested_session():
                async with session.begin_nested():
                    yield session

            for module in (memory_extractor, memory_store, background_job_store, memory_lifecycle_store):
                monkeypatch.setattr(module, "get_db_session", nested_session)
            try:
                yield session
            finally:
                await session.close()
        finally:
            await outer.rollback()
    await database.close_db()


async def test_delete_all_cancels_old_jobs_and_fences_delayed_enqueue(memory_database):
    from travel_agent.memory.memory_extractor import MemoryExtractionFailed, MemoryExtractor
    from travel_agent.memory.memory_store import MemoryStore
    from travel_agent.runtime.job_contracts import BackgroundJobType
    from travel_agent.storage.background_job_store import BackgroundJobStore
    from travel_agent.storage.memory_lifecycle_store import MemoryLifecycleStore

    session = memory_database
    await session.execute(text("""
        INSERT INTO user_profiles (user_id, preferences, auto_portrait, revision)
        VALUES ('b6-user', '{"pace":"轻松悠闲"}', 'old portrait', 3)
    """))
    await session.execute(text("""
        INSERT INTO memory_facts (user_id, session_id, content, category, importance)
        VALUES ('b6-user', 'session', 'old fact', 'preference', 5)
    """))
    jobs = BackgroundJobStore()
    payload = {"user_id": "b6-user", "session_id": "session", "portrait_baseline": "old portrait"}
    old_job, _ = await jobs.enqueue(BackgroundJobType.MEMORY_EXTRACTION, "old-turn", payload)
    (running,) = await jobs.claim(lease_seconds=60)
    assert running.job_id == old_job.job_id
    dead_job, _ = await jobs.enqueue(BackgroundJobType.MEMORY_EXTRACTION, "dead-turn", payload)
    await session.execute(
        text("UPDATE background_jobs SET status = 'dead' WHERE job_id = :job_id"),
        {"job_id": dead_job.job_id},
    )

    summary = await MemoryLifecycleStore().delete_all_user_memory(user_id="b6-user")
    assert summary.affected_facts == 1
    assert (await session.execute(text("SELECT count(*) FROM memory_facts"))).scalar_one() == 0
    profile = (await session.execute(text("SELECT preferences, auto_portrait, revision FROM user_profiles"))).one()
    assert profile.preferences == {"pace": "轻松悠闲"} and profile.auto_portrait == ""
    job_rows = (await session.execute(text("SELECT status, payload FROM background_jobs"))).all()
    assert all(row.status == "cancelled" and "portrait_baseline" not in row.payload for row in job_rows)
    assert not await jobs.retry_dead(dead_job.job_id)
    assert not await jobs.enqueue_memory_extraction("late-old-turn", payload, memory_revision_at_start=3)
    assert await jobs.enqueue_memory_extraction("new-turn", payload, memory_revision_at_start=profile.revision)
    with pytest.raises(MemoryExtractionFailed, match="租约"):
        await MemoryExtractor()._commit_extraction(
            job=running, user_id="b6-user", session_id="session", source_message_id="message",
            facts=[], embeddings=[], portrait=[], store=MemoryStore(),
        )


async def test_delete_all_failure_rolls_back_jobs_and_facts(memory_database, monkeypatch):
    from travel_agent.memory.memory_graph import MemoryGraph
    from travel_agent.runtime.job_contracts import BackgroundJobType
    from travel_agent.storage.background_job_store import BackgroundJobStore
    from travel_agent.storage.memory_lifecycle_store import MemoryLifecycleStore

    await memory_database.execute(text("""
        INSERT INTO memory_facts (user_id, session_id, content, category, importance)
        VALUES ('b6-failure', 'session', 'preserve', 'preference', 5)
    """))
    jobs = BackgroundJobStore()
    job, _ = await jobs.enqueue(BackgroundJobType.MEMORY_EXTRACTION, "rollback-turn", {"user_id": "b6-failure"})

    async def fail(*args, **kwargs):
        raise RuntimeError("graph failure")

    monkeypatch.setattr(MemoryGraph, "delete_user_graph", fail)
    with pytest.raises(RuntimeError, match="graph failure"):
        await MemoryLifecycleStore().delete_all_user_memory(user_id="b6-failure")
    assert (await memory_database.execute(text("SELECT count(*) FROM memory_facts"))).scalar_one() == 1
    assert (await jobs.get(job.job_id)).status.value == "pending"
