"""在当前配置库的临时表中验证记忆写入；外层事务始终回滚。"""

from contextlib import asynccontextmanager
import os
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from travel_agent.storage import database

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(os.getenv("JP_MEMORY_EXTRACTION_ROLLBACK_TESTS") != "1", reason="需要显式启用配置库的临时表验证"),
]


@pytest.fixture
async def memory_database(monkeypatch):
    from travel_agent.memory import manual_facts, memory_extractor, memory_store, user_profile

    engine = database.get_engine()
    async with engine.connect() as connection:
        outer = await connection.begin()
        try:
            for name in ("background_jobs", "user_profiles", "memory_facts", "memory_entities", "memory_relations"):
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
                await connection.execute(text(f"CREATE TEMP SEQUENCE {name}_extraction_sequence"))
                await connection.execute(text(
                    f"ALTER TABLE {name} ALTER COLUMN {field} SET DEFAULT nextval('pg_temp.{name}_extraction_sequence')"
                ))
            await connection.execute(text("SET LOCAL search_path = pg_temp, public"))
            session = AsyncSession(bind=connection, expire_on_commit=False)

            @asynccontextmanager
            async def nested_session():
                async with session.begin_nested():
                    yield session

            for module in (manual_facts, memory_extractor, memory_store, user_profile):
                monkeypatch.setattr(module, "get_db_session", nested_session)
            monkeypatch.setattr(memory_store, "get_settings", lambda: SimpleNamespace(
                embedding=SimpleNamespace(enabled=False)
            ))
            monkeypatch.setattr(manual_facts, "get_settings", lambda: SimpleNamespace(
                embedding=SimpleNamespace(enabled=False)
            ))
            try:
                yield session
            finally:
                await session.close()
        finally:
            await outer.rollback()
    await database.close_db()


async def _job(session):
    from travel_agent.runtime.job_contracts import BackgroundJob, BackgroundJobStatus, BackgroundJobType

    await session.execute(text("""
        INSERT INTO background_jobs (job_id, job_type, dedupe_key, status, lease_owner, lease_expires_at)
        VALUES ('job-extraction', 'memory_extraction', 'turn-extraction', 'running', 'owner-1', NOW() + INTERVAL '1 minute')
    """))
    return BackgroundJob(
        job_id="job-extraction", job_type=BackgroundJobType.MEMORY_EXTRACTION,
        dedupe_key="turn-extraction", status=BackgroundJobStatus.RUNNING, lease_owner="owner-1",
    )


async def _apply(job, *, content="吃素", portrait=None):
    from travel_agent.memory import memory_extractor
    from travel_agent.memory.memory_extractor import ExtractedFactCandidate, MemoryExtractor
    from travel_agent.memory.memory_store import MemoryStore

    extractor = MemoryExtractor()
    store = MemoryStore()
    async with memory_extractor.get_db_session() as session:
        context = await extractor._load_context("local", store=store, db_session=session)
    return await extractor._commit_extraction(
        job=job, user_id="local", session_id="session", source_message_id="message",
        facts=[ExtractedFactCandidate(content=content, category="preference", importance=5)],
        embeddings=[None], portrait=portrait or [], store=store, context=context,
    )


async def test_reclaimed_job_reuses_the_committed_effects(memory_database):
    session = memory_database
    job = await _job(session)
    portrait = [{"trait": "素食", "dimension": "lifestyle", "evidence": "吃素"}]
    first = await _apply(job, portrait=portrait)
    await session.execute(text("UPDATE background_jobs SET lease_owner = 'owner-2'"))
    retry = await _apply(job.model_copy(update={"lease_owner": "owner-2"}), content="另一种措辞")

    assert retry == first
    assert (await session.execute(text("SELECT content FROM memory_facts"))).scalars().all() == ["吃素"]
    assert (await session.execute(text("SELECT COUNT(*) FROM memory_relations"))).scalar_one() == 1
    assert "素食" in (await session.execute(text("SELECT auto_portrait FROM user_profiles"))).scalar_one()


async def test_failed_portrait_write_rolls_back_facts_and_job_marker(memory_database, monkeypatch):
    from travel_agent.memory.memory_graph import MemoryGraph

    session = memory_database
    job = await _job(session)

    async def fail(*args, **kwargs):
        raise RuntimeError("graph failed")

    monkeypatch.setattr(MemoryGraph, "update_portrait", fail)
    with pytest.raises(RuntimeError, match="graph failed"):
        await _apply(job, portrait=[{"trait": "素食", "dimension": "lifestyle"}])
    assert (await session.execute(text("SELECT COUNT(*) FROM memory_facts"))).scalar_one() == 0
    assert (await session.execute(text("SELECT COUNT(*) FROM user_profiles"))).scalar_one() == 0
    assert (await session.execute(text("SELECT result FROM background_jobs"))).scalar_one() is None


async def test_lost_lease_cannot_apply_a_new_result(memory_database):
    from travel_agent.memory.memory_extractor import MemoryExtractionFailed

    session = memory_database
    job = await _job(session)
    await session.execute(text("UPDATE background_jobs SET lease_owner = 'replacement'"))
    with pytest.raises(MemoryExtractionFailed, match="租约"):
        await _apply(job)
    assert (await session.execute(text("SELECT COUNT(*) FROM memory_facts"))).scalar_one() == 0


async def test_profile_field_updates_preserve_other_fields(memory_database):
    from travel_agent.memory.user_profile import UserProfileMemory

    profiles = UserProfileMemory()
    await profiles.update_preferences("local", {"travel_styles": ["文化探索"]})
    await profiles.set_auto_portrait("local", "生活方式：素食")
    await profiles.update_preferences("local", {"pace": "轻松悠闲"})
    await profiles.ensure_profile_for_write("local")
    profile = await profiles.get_user_profile("local")
    assert profile.preferences.travel_styles == ["文化探索"]
    assert profile.preferences.pace == "轻松悠闲"
    assert profile.auto_portrait == "生活方式：素食"


async def test_manual_fact_deduplication_in_configured_database(memory_database):
    from travel_agent.memory.manual_facts import save_manual_fact
    from travel_agent.memory.memory_store import MemoryStore
    from travel_agent.memory.user_profile import UserProfileMemory

    args = {"store": MemoryStore(), "user_id": "local", "content": "不吃海鲜",
            "category": "constraint", "profile_for_write": UserProfileMemory}
    first = await save_manual_fact(**args)
    second = await save_manual_fact(**args)
    assert first.status == "created" and second.status == "existing"
    assert first.fact["fact_id"] == second.fact["fact_id"]
    assert (await memory_database.execute(text("SELECT COUNT(*) FROM memory_facts"))).scalar_one() == 1
    history = await UserProfileMemory().get_memory_management_history("local")
    assert [event["operation"] for event in history] == ["add_fact", "add_fact"]
    assert [event["details"]["status"] for event in history] == ["created", "existing"]
    assert (await memory_database.execute(text("SELECT memory_revision FROM memory_facts"))).scalar_one() == history[-1]["revision"]


async def test_explicit_change_updates_fact_and_removes_stale_portrait(memory_database):
    from travel_agent.memory.memory_extractor import ExtractedFactCandidate, MemoryExtractor
    from travel_agent.memory.memory_graph import MemoryGraph
    from travel_agent.memory.memory_store import MemoryStore, USER_MANUAL_SESSION_ID
    from travel_agent.memory.user_profile import UserProfileMemory

    session = memory_database
    fact_id, created_before = (await session.execute(text("""
        INSERT INTO memory_facts (user_id, session_id, content, category, importance, created_at)
        VALUES ('local', :manual, '吃素', 'preference', 5, NOW() - INTERVAL '30 days')
        RETURNING fact_id, created_at
    """), {"manual": USER_MANUAL_SESSION_ID})).one()
    graph = MemoryGraph()
    await graph.update_portrait("local", [{"trait": "素食", "dimension": "lifestyle"}], db_session=session)
    await UserProfileMemory().set_auto_portrait("local", "生活方式：素食", db_session=session)
    job = (await _job(session)).model_copy(update={"payload": {"memory_revision_at_start": 1}})
    extractor, store = MemoryExtractor(), MemoryStore()
    context = await extractor._load_context("local", store=store, db_session=session)
    relation_id = int(context.relations[0]["relation_id"])
    outcome = await extractor._commit_extraction(
        job=job, user_id="local", session_id="session", source_message_id="message",
        facts=[ExtractedFactCandidate(action="update", fact_id=str(fact_id), content="不再吃素",
                                      category="preference", importance=5)],
        embeddings=[None], portrait=[], store=store, context=context, deleted_relation_ids=[relation_id],
    )
    row = (await session.execute(text(
        "SELECT content, session_id, memory_revision, created_at FROM memory_facts WHERE fact_id = :id"
    ), {"id": fact_id})).one()
    assert row.content == "不再吃素" and row.session_id == USER_MANUAL_SESSION_ID and row.memory_revision > 0
    # 被明确意愿更新的事实按更新时间参与新近度排序和冲突仲裁，而不是停留在首次创建时间。
    assert row.created_at > created_before
    assert (await UserProfileMemory().get_user_profile("local")).auto_portrait == ""
    assert outcome.facts_written == 1 and outcome.portraits_deleted == 1
