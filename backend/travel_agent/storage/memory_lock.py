"""串行化同一用户的记忆删除与抽取任务入队。"""

from sqlalchemy import text


async def lock_user_memory(session, user_id: str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"memory-lifecycle:{user_id}"},
    )
