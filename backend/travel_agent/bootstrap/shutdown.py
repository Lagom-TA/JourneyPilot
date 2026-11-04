"""先停止生产者，再关闭其持久化资源。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from travel_agent.bootstrap.registry import clear_components, registered_components
from travel_agent.runtime.run_lease import release_all_leases

if TYPE_CHECKING:
    from travel_agent.bootstrap.components import AppComponents

logger = logging.getLogger(__name__)


async def shutdown_components(components: AppComponents | None = None) -> None:
    """交还租约与停止生产者都发生在数据库连接池关闭之前。"""
    if components is None:
        components = registered_components()
    failures: list[Exception] = []
    if components:
        for name, service in (
            ("后台任务", components.background_job_worker),
            ("运行恢复", components.run_recovery_service),
        ):
            if service is None:
                continue
            try:
                await service.stop()
            except Exception as exc:
                logger.error("%s停止失败: %s", name, exc, exc_info=True)
                failures.append(exc)

        try:
            await components.mcp_manager.close_all_sessions()
        except Exception as exc:
            logger.warning("MCP 会话关闭失败: %s", exc)

        if components.usage_flush_service is not None:
            try:
                await components.usage_flush_service.stop()
            except Exception as exc:
                logger.error("用量刷写停止失败: %s", exc, exc_info=True)
                failures.append(exc)
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

    if registered_components() is components:
        clear_components()
    if failures:
        raise failures[0]
