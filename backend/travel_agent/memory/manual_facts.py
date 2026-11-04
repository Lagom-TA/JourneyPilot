"""幂等的手动记忆创建，并按身份读回。"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import text

from travel_agent.config.loader import get_settings
from travel_agent.memory.memory_store import (
    USER_MANUAL_IMPORTANCE,
    USER_MANUAL_SESSION_ID,
    MemoryStore,
)
from travel_agent.memory.user_profile import UserProfileMemory
from travel_agent.storage.database import get_db_session


class ManualFactSaveFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class ManualFactResult:
    status: str
    fact: dict


async def save_manual_fact(
    *,
    store: MemoryStore,
    user_id: str,
    content: str,
    category: str,
    profile_for_write: Callable[[], UserProfileMemory],
) -> ManualFactResult:
    existing = await store.find_manual_fact(user_id, content)
    if existing is not None:
        return ManualFactResult(status="existing", fact=existing)
    embedding = await store._compute_embedding(content) if get_settings().embedding.enabled else None
    async with get_db_session() as session:
        # 同一用户与正文的并发请求先串行，再重新检查是否已经写入。
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"manual-memory:{user_id}:{content}"},
        )
        existing = await store.find_manual_fact(user_id, content, db_session=session)
        if existing is not None:
            return ManualFactResult(status="existing", fact=existing)
        fact_id = await store.save_fact(
            user_id=user_id,
            session_id=USER_MANUAL_SESSION_ID,
            content=content,
            category=category,
            importance=USER_MANUAL_IMPORTANCE,
            db_session=session,
            prepared_embedding=embedding,
        )
        if fact_id is None:
            raise ManualFactSaveFailed("memory fact save failed")
        await profile_for_write().ensure_profile_for_write(user_id, db_session=session)
        created = await store.get_fact(user_id, fact_id, db_session=session)
        if created is None:
            raise ManualFactSaveFailed("memory fact save failed")
        return ManualFactResult(status="created", fact=created)
