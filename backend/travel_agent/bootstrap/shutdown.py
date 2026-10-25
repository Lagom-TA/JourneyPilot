"""Stop producers before closing their persistent resources."""

import logging

from travel_agent.bootstrap.registry import registered_components
from travel_agent.runtime.run_lease import release_all_leases

logger = logging.getLogger(__name__)


async def shutdown_components() -> None:
    """Lease release and producer shutdown still need open database pools."""
    components = registered_components()
    if components and components.usage_flush_service is not None:
        await components.usage_flush_service.stop()
    if components and components.background_job_worker is not None:
        await components.background_job_worker.stop()
    if components and components.run_recovery_service is not None:
        await components.run_recovery_service.stop()
    try:
        released = await release_all_leases()
        if released:
            logger.info("已交还 %d 个执行租约", released)
    except Exception as e:
        logger.warning(f"执行租约交还失败: {e}")

    if components and components._checkpointer_pool is not None:
        try:
            await components._checkpointer_pool.close()
        except Exception as e:
            logger.warning(f"LangGraph checkpointer 连接池关闭失败: {e}")

    try:
        from travel_agent.storage.database import close_db

        await close_db()
    except Exception as e:
        logger.warning(f"数据库关闭失败: {e}")

    try:
        from travel_agent.storage.redis_client import close_redis

        await close_redis()
    except Exception as e:
        logger.warning(f"Redis 关闭失败: {e}")
