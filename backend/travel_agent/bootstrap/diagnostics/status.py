"""组合当前应用状态，不依赖 API schema。"""

from travel_agent.bootstrap.diagnostics.dependencies import (
    _probe_database,
    _probe_redis,
)
from travel_agent.bootstrap.registry import get_components


async def collect_status():
    """获取系统状态"""
    components = get_components()

    # 检查数据库连接
    db_ok, _ = await _probe_database()

    # 检查 Redis 连接
    redis_ok, _ = await _probe_redis()

    # 记忆抽取管线累计计数：抽取本身的成败；任务积压在 /health/ready 的 background_jobs。
    from travel_agent.memory.extraction_stats import get_memory_extraction_stats

    return dict(
        status="running",
        tools_count=components.tool_registry.count,
        db_connected=db_ok,
        redis_connected=redis_ok,
        memory_extraction=get_memory_extraction_stats().snapshot(),
    )
