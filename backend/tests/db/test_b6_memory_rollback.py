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
    from travel_agent.memory import manual_facts, memory_extractor, memory_store, user_profile
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
            await connection.execute(text(
                "ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS "
                "memory_management_history JSONB NOT NULL DEFAULT '[]'::jsonb"
            ))
            await connection.execute(text(
                "ALTER TABLE memory_facts ADD COLUMN IF NOT EXISTS memory_revision INTEGER NOT NULL DEFAULT 0"
            ))
            await connection.execute(text(
                "ALTER TABLE memory_relations ADD COLUMN IF NOT EXISTS memory_revision INTEGER NOT NULL DEFAULT 0"
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

            for module in (manual_facts, memory_extractor, memory_store, user_profile, background_job_store, memory_lifecycle_store):
                monkeypatch.setattr(module, "get_db_session", nested_session)
            try:
                yield session
            finally:
                await session.close()
        finally:
            await outer.rollback()
    await database.close_db()


async def test_delete_all_cancels_old_jobs_and_fences_delayed_enqueue(memory_database):
    from travel_agent.memory.memory_extractor import MemoryExtractionContext, MemoryExtractionFailed, MemoryExtractor
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
            context=MemoryExtractionContext([], [], [], "", 0),
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


async def test_delete_one_duplicate_audit_rolls_back_fact(memory_database):
    from travel_agent.storage.memory_lifecycle_store import MemoryLifecycleStore

    store = MemoryLifecycleStore()
    await store.delete_by_category(user_id="b5-one", category="unused", request_id="b5-request")
    fact_id = (await memory_database.execute(text("""
        INSERT INTO memory_facts (user_id, session_id, content, category, importance)
        VALUES ('b5-one', 'session', 'preserve', 'preference', 5)
        RETURNING fact_id
    """))).scalar_one()

    with pytest.raises(ValueError, match="request_id"):
        await store.delete_one_fact(user_id="b5-one", fact_id=str(fact_id), request_id="b5-request")
    assert (await memory_database.execute(text("SELECT count(*) FROM memory_facts"))).scalar_one() == 1


async def test_delete_category_failure_rolls_back_facts(memory_database, monkeypatch):
    from travel_agent.memory.memory_graph import MemoryGraph
    from travel_agent.storage.memory_lifecycle_store import MemoryLifecycleStore

    await memory_database.execute(text("""
        INSERT INTO memory_facts (user_id, session_id, content, category, importance)
        VALUES ('b5-category', 'session', 'preserve', 'preference', 5)
    """))

    async def fail(*args, **kwargs):
        raise RuntimeError("graph failure")

    monkeypatch.setattr(MemoryGraph, "delete_user_graph", fail)
    with pytest.raises(RuntimeError, match="graph failure"):
        await MemoryLifecycleStore().delete_by_category(
            user_id="b5-category", category="preference", clear_graph=True,
        )
    assert (await memory_database.execute(text("SELECT count(*) FROM memory_facts"))).scalar_one() == 1
    assert (await memory_database.execute(text("SELECT count(*) FROM memory_forgetting_audits"))).scalar_one() == 0


async def test_manual_delete_retries_stale_extraction_without_cancelling_it(memory_database, monkeypatch):
    from types import SimpleNamespace
    from travel_agent.memory import memory_store
    from travel_agent.memory.memory_extractor import ExtractedFactCandidate, MemoryExtractionFailed, MemoryExtractor
    from travel_agent.memory.memory_store import MemoryStore
    from travel_agent.memory.user_profile import UserProfileMemory
    from travel_agent.runtime.job_contracts import BackgroundJobType
    from travel_agent.storage.background_job_store import BackgroundJobStore
    from travel_agent.storage.memory_lifecycle_store import MemoryLifecycleStore

    monkeypatch.setattr(memory_store, "get_settings", lambda: SimpleNamespace(
        embedding=SimpleNamespace(enabled=False)
    ))
    fact_id = (await memory_database.execute(text("""
        INSERT INTO memory_facts (user_id, session_id, content, category, importance)
        VALUES ('b5-race', 'session', '不吃辣', 'preference', 5)
        RETURNING fact_id
    """))).scalar_one()
    jobs = BackgroundJobStore()
    await jobs.enqueue(BackgroundJobType.MEMORY_EXTRACTION, "b5-race-turn", {"user_id": "b5-race"})
    (job,) = await jobs.claim(lease_seconds=60)
    extractor, store = MemoryExtractor(), MemoryStore()
    old_context = await extractor._load_context("b5-race", store=store, db_session=memory_database)

    await MemoryLifecycleStore().delete_one_fact(
        user_id="b5-race", fact_id=str(fact_id), reason="remove memory fact: 不吃辣",
    )
    history = await UserProfileMemory().get_memory_management_history("b5-race", db_session=memory_database)
    assert history[-1]["operation"] == "delete_fact"
    assert history[-1]["items"][0]["content"] == "不吃辣"
    audit_metadata = (await memory_database.execute(text("SELECT metadata FROM memory_forgetting_audits"))).scalar_one()
    assert "不吃辣" not in str(audit_metadata)
    candidate = ExtractedFactCandidate(content="喜欢拍照", category="preference", importance=5)
    with pytest.raises(MemoryExtractionFailed, match="手动管理记录已变化"):
        await extractor._commit_extraction(
            job=job, user_id="b5-race", session_id="session", source_message_id="message",
            facts=[candidate], embeddings=[None], portrait=[], store=store, context=old_context,
        )
    assert (await jobs.get(job.job_id)).status.value == "running"
    new_context = await extractor._load_context("b5-race", store=store, db_session=memory_database)
    await extractor._commit_extraction(
        job=job, user_id="b5-race", session_id="session", source_message_id="message",
        facts=[candidate], embeddings=[None], portrait=[], store=store, context=new_context,
    )
    assert (await memory_database.execute(text("SELECT content FROM memory_facts"))).scalars().all() == ["喜欢拍照"]


async def test_preference_change_invalidates_inflight_extraction(memory_database):
    from travel_agent.memory.memory_extractor import ExtractedFactCandidate, MemoryExtractionFailed, MemoryExtractor
    from travel_agent.memory.memory_store import MemoryStore
    from travel_agent.memory.user_profile import UserProfileMemory
    from travel_agent.runtime.job_contracts import BackgroundJobType
    from travel_agent.storage.background_job_store import BackgroundJobStore

    jobs = BackgroundJobStore()
    await jobs.enqueue(BackgroundJobType.MEMORY_EXTRACTION, "b5-prefs", {"user_id": "b5-prefs"})
    (job,) = await jobs.claim(lease_seconds=60)
    extractor, store = MemoryExtractor(), MemoryStore()
    context = await extractor._load_context("b5-prefs", store=store, db_session=memory_database)
    await UserProfileMemory().update_preferences("b5-prefs", {"pace": "轻松悠闲"})
    with pytest.raises(MemoryExtractionFailed, match="记录已变化"):
        await extractor._commit_extraction(
            job=job, user_id="b5-prefs", session_id="session", source_message_id="message",
            facts=[ExtractedFactCandidate(content="喜欢拍照", category="preference", importance=5)],
            embeddings=[None], portrait=[], store=store, context=context,
        )
    assert (await memory_database.execute(text("SELECT count(*) FROM memory_facts"))).scalar_one() == 0


async def test_delete_all_clears_manual_history_content(memory_database):
    from travel_agent.memory.user_profile import UserProfileMemory
    from travel_agent.storage.memory_lifecycle_store import MemoryLifecycleStore

    await memory_database.execute(text("""
        INSERT INTO user_profiles (user_id, memory_management_history)
        VALUES ('b5-clear', CAST(:history AS jsonb))
    """), {"history": '[{"operation":"delete_fact","revision":1,"items":[{"content":"旧内容"}]}]'})
    await MemoryLifecycleStore().delete_all_user_memory(user_id="b5-clear")
    history = await UserProfileMemory().get_memory_management_history("b5-clear", db_session=memory_database)
    assert len(history) == 1 and history[0]["operation"] == "clear_all" and history[0]["items"] == []
    assert "旧内容" not in str(history)


async def test_manual_add_delete_and_readd_are_recorded_in_order(memory_database, monkeypatch):
    from types import SimpleNamespace
    from travel_agent.memory import manual_facts, memory_store
    from travel_agent.memory.manual_facts import save_manual_fact
    from travel_agent.memory.memory_store import MemoryStore
    from travel_agent.memory.user_profile import UserProfileMemory
    from travel_agent.storage.memory_lifecycle_store import MemoryLifecycleStore

    settings = SimpleNamespace(embedding=SimpleNamespace(enabled=False))
    monkeypatch.setattr(manual_facts, "get_settings", lambda: settings)
    monkeypatch.setattr(memory_store, "get_settings", lambda: settings)
    args = {"store": MemoryStore(), "user_id": "b5-history", "content": "不吃辣",
            "category": "preference", "profile_for_write": UserProfileMemory}
    first = await save_manual_fact(**args)
    await MemoryLifecycleStore().delete_one_fact(user_id="b5-history", fact_id=first.fact["fact_id"])
    second = await save_manual_fact(**args)
    history = await UserProfileMemory().get_memory_management_history("b5-history", db_session=memory_database)
    assert [event["operation"] for event in history] == ["add_fact", "delete_fact", "add_fact"]
    assert [event["revision"] for event in history] == sorted(event["revision"] for event in history)
    assert all(event["items"][0]["content"] == "不吃辣" for event in history)
    assert second.fact["memory_revision"] == history[-1]["revision"]


async def test_extraction_receives_manual_history_and_saves_other_fact(memory_database, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from travel_agent.config import loader
    from travel_agent.memory import memory_store
    from travel_agent.memory.memory_extractor import MemoryExtractor
    from travel_agent.runtime.job_contracts import BackgroundJobType
    from travel_agent.storage.background_job_store import BackgroundJobStore
    from travel_agent.storage.memory_lifecycle_store import MemoryLifecycleStore

    settings = SimpleNamespace(embedding=SimpleNamespace(enabled=False))
    monkeypatch.setattr(loader, "get_settings", lambda: settings)
    monkeypatch.setattr(memory_store, "get_settings", lambda: settings)
    fact_id = (await memory_database.execute(text("""
        INSERT INTO memory_facts (user_id, session_id, content, category, importance)
        VALUES ('b5-input', 'session', '不吃辣', 'preference', 5) RETURNING fact_id
    """))).scalar_one()
    await MemoryLifecycleStore().delete_one_fact(user_id="b5-input", fact_id=str(fact_id))
    jobs = BackgroundJobStore()
    await jobs.enqueue(BackgroundJobType.MEMORY_EXTRACTION, "b5-input-turn", {
        "user_id": "b5-input", "memory_revision_at_start": 0,
    })
    (job,) = await jobs.claim(lease_seconds=60)
    extractor = MemoryExtractor()
    extractor._call_llm = AsyncMock(return_value={
        "facts": [{"content": "喜欢拍照", "category": "preference", "importance": 6}],
        "portrait": [],
    })
    outcome = await extractor.extract_from_turn(
        "b5-input", "session", "不吃辣，也喜欢拍照", source_message_id="message", job=job,
    )
    context = extractor._call_llm.await_args.args[1]
    assert context.management_history[-1]["items"][0]["content"] == "不吃辣"
    assert outcome.facts_written == 1
    assert (await memory_database.execute(text("SELECT content FROM memory_facts"))).scalars().all() == ["喜欢拍照"]
