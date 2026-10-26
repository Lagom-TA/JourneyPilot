"""幂等的手动记忆创建，并按身份读回。"""

from collections.abc import Callable
from dataclasses import dataclass

from travel_agent.memory.memory_store import (
    USER_MANUAL_IMPORTANCE,
    USER_MANUAL_SESSION_ID,
    MemoryStore,
)
from travel_agent.memory.user_profile import UserProfileMemory


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
    fact_id = await store.save_fact(
        user_id=user_id,
        session_id=USER_MANUAL_SESSION_ID,
        content=content,
        category=category,
        importance=USER_MANUAL_IMPORTANCE,
    )
    if fact_id is None:
        raise ManualFactSaveFailed("memory fact save failed")
    # 仅在真实写入后解析画像；读取与失败不创建空画像。
    await profile_for_write().ensure_profile_for_write(user_id)
    created = await store.get_fact(user_id, fact_id)
    if created is None:
        raise ManualFactSaveFailed("memory fact save failed")
    return ManualFactResult(status="created", fact=created)
