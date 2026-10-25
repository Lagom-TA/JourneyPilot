import pytest
from sqlalchemy import text

from travel_agent.config.loader import get_settings
from travel_agent.storage.database import get_db_session
from travel_agent.memory.memory_store import MemoryStore, USER_MANUAL_SESSION_ID

pytestmark = pytest.mark.postgres


async def test_manual_preference_survives_without_embeddings(migrated_async_database, monkeypatch):
    monkeypatch.setattr(get_settings().embedding, "enabled", False)
    store = MemoryStore()

    fact_id = await store.save_fact("local", USER_MANUAL_SESSION_ID, "不要海鲜", importance=10)

    assert fact_id is not None
    fact = await store.get_fact("local", fact_id)
    assert fact["content"] == "不要海鲜"
    assert fact["source"] == "manual"
    manual_facts = await store.list_manual_facts("local", limit=10)
    assert [(item["fact_id"], item["content"]) for item in manual_facts] == [
        (str(fact_id), "不要海鲜")
    ]
    async with get_db_session() as session:
        result = await session.execute(
            text("SELECT embedding IS NULL FROM memory_facts WHERE fact_id = :id"),
            {"id": fact_id},
        )
    assert result.scalar_one() is True
