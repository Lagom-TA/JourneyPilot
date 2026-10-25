"""Dependency connectivity and startup schema diagnostics."""

from __future__ import annotations

from typing import Any, Dict, Tuple

from sqlalchemy import text

from travel_agent.llm.router import get_model_router


async def _probe_database() -> Tuple[bool, str]:
    """Connectivity is independent of the startup schema contract."""

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
    """Reuse the startup report; missing evidence blocks readiness."""

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
