"""LangGraph Postgres checkpointer 的构建。

业务数据使用 SQLAlchemy/asyncpg 连接池。LangGraph 的 AsyncPostgresSaver 需要
psycopg3，因此 checkpoint 使用同一数据库上的独立小连接池。

**最终事实：** 用户可见的行程事实由 ``TripRun`` 与 Delivery Bundle store
（SQLAlchemy）保存；checkpoint 行只用于执行恢复。它与 Bundle/TripRun 的提交
不在同一事务中（独立连接池，``autocommit=True``）。崩溃后恢复与 finalizer
必须以 store 状态为准；``run_id:delivery:create`` 的幂等性吸收重复的 finalizer
尝试。不能假设 checkpoint 已越过 finalizer 就等于 Bundle 已提交，反之亦然。
"""

from __future__ import annotations

import logging
from typing import Tuple

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from ..config.models import Settings
from .maintenance.checkpoint_schema import missing_checkpoint_tables_async
from travel_agent.storage.checkpoint_logging import install_checkpoint_serde_log_dedup

logger = logging.getLogger(__name__)


async def build_checkpointer(
    settings: Settings,
) -> Tuple[AsyncPostgresSaver, AsyncConnectionPool]:
    """把 LangGraph Postgres checkpointer 绑定到已迁移的数据库。

    刻意不调用 ``setup()``：建表属于 DDL，由 ``journeypilot migrate`` 负责。
    缺表时在这里抛错，使未迁移的数据库在启动时暴露，而不是第一次 interrupt 时。

    构建 saver 也是其序列化器日志噪声的起点，因此在这里安装去重过滤器：无论
    服务应用、演练脚本还是种子脚本，构建 checkpointer 都经过这一处。安装是
    幂等的，只改 logging；序列化器本身不改动（配置
    ``allowed_msgpack_modules`` 白名单会切换到严格模式，未列出的类型在恢复时
    会被静默降级为普通 dict，而不是抛错）。
    """
    install_checkpoint_serde_log_dedup()

    connection_kwargs = {
        "autocommit": True,
        "prepare_threshold": 0,
        "row_factory": dict_row,
    }
    pool = AsyncConnectionPool(
        conninfo=settings.database.sync_url,
        min_size=1,
        max_size=settings.database.pool_size,
        kwargs=connection_kwargs,
        open=False,
    )
    await pool.open()

    try:
        async with pool.connection() as conn:
            missing = await missing_checkpoint_tables_async(conn)
        if missing:
            raise RuntimeError(
                "LangGraph checkpoint 表缺失（" + "、".join(missing) + "）。"
                "它们由启动编排器建立，API 进程不建表 —— 先跑 `journeypilot migrate`。"
            )
        checkpointer = AsyncPostgresSaver(pool)
        logger.info("LangGraph Postgres checkpointer 已就绪")
        return checkpointer, pool
    except Exception:
        await pool.close()
        raise
