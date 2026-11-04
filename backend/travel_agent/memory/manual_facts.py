"""幂等的手动记忆创建，并按身份读回。"""

from collections.abc import Callable
from dataclasses import dataclass

from travel_agent.config.loader import get_settings
from travel_agent.memory.memory_store import (
    USER_MANUAL_IMPORTANCE,
    USER_MANUAL_SESSION_ID,
    MemoryStore,
)
from travel_agent.memory.user_profile import UserProfileMemory
from travel_agent.storage.database import get_db_session
from travel_agent.storage.memory_lock import lock_user_memory


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
    embedding = None
    embedding_enabled = get_settings().embedding.enabled
    while True:
        async with get_db_session() as session:
            await lock_user_memory(session, user_id)
            existing = await store.find_manual_fact(user_id, content, db_session=session)
            if existing is not None:
                revision = await profile_for_write().record_memory_management(
                    user_id, "add_fact", db_session=session,
                    items=[{"fact_id": existing["fact_id"], "content": content,
                            "category": existing.get("category") or category}],
                    details={"status": "existing"},
                )
                await store.set_memory_revision(user_id, existing["fact_id"], revision, db_session=session)
                return ManualFactResult(status="existing", fact=existing)
            if not embedding_enabled or embedding is not None:
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
                revision = await profile_for_write().record_memory_management(
                    user_id, "add_fact", db_session=session,
                    items=[{"fact_id": fact_id, "content": content, "category": category}],
                    details={"status": "created"},
                )
                await store.set_memory_revision(user_id, fact_id, revision, db_session=session)
                created = await store.get_fact(user_id, fact_id, db_session=session)
                if created is None:
                    raise ManualFactSaveFailed("memory fact save failed")
                return ManualFactResult(status="created", fact=created)
        # 模型或向量服务不能在用户级事务锁内调用。
        embedding = await store._compute_embedding(content)
