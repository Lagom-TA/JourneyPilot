"""依赖连通性与启动时的 schema 诊断。"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from sqlalchemy import text

from travel_agent.llm.router import get_model_router


async def _probe_database() -> Tuple[bool, str]:
    """只验证连接可用，与启动时的 schema 合同校验无关。"""

    try:
        from travel_agent.storage.database import get_engine

        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


async def _probe_redis() -> Tuple[bool, str]:
    try:
        from travel_agent.storage.redis_client import get_redis

        await get_redis().ping()
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def _probe_model_config() -> Tuple[bool, str]:
    try:
        router = get_model_router()
        router.get_primary()
        router.get_fast()
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def _probe_schema_report(components: Any) -> Dict[str, Any]:
    """复用启动时的校验报告；报告缺失即视为未就绪。"""

    from travel_agent.storage.maintenance.report import GATES_READINESS

    report = getattr(components, "schema_report", None)
    if report is None:
        return {
            "ready": False,
            "gates_readiness": GATES_READINESS,
            "available": False,
            "message": "启动时未执行数据库合同校验（详见启动日志）",
        }
    return {"ready": report.compatible, "available": True, **report.to_dict()}
