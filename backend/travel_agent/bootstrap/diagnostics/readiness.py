"""Compose readiness from blocking dependencies and nonblocking diagnostics."""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from travel_agent.bootstrap.diagnostics.dependencies import (
    _probe_database,
    _probe_model_config,
    _probe_redis,
    _probe_schema_report,
)
from travel_agent.bootstrap.diagnostics.knowledge import (
    _probe_data_snapshots,
    _probe_knowledge_corpus,
    _probe_pdf_export,
)
from travel_agent.bootstrap.diagnostics.runtime import (
    _probe_background_jobs,
    _probe_resource_limits,
    _probe_run_execution,
)
from travel_agent.bootstrap.registry import get_components
from travel_agent.config import get_settings
from travel_agent.config.capabilities import capability_report

_NON_BLOCKING_COMPONENTS = frozenset(
    {
        "mcp",
        "data_snapshots",
        "knowledge_corpus",
        "run_execution",
        "background_jobs",
        "resource_limits",
        "pdf_export",
    }
)


async def collect_readiness() -> Dict[str, Any]:
    """生产就绪探针：核心依赖不可用时返回 503。"""
    settings = get_settings()
    components = get_components()

    db_ok, db_message = await _probe_database()
    redis_ok, redis_message = await _probe_redis()
    model_ok, model_message = _probe_model_config()

    gates_enabled = bool(settings.run_control.plan_gate_enabled)
    checkpointer_ok = bool(components.checkpointer) or not gates_enabled
    checkpointer_message = (
        "ok"
        if checkpointer_ok
        else "run-control gates are enabled but LangGraph checkpointer is unavailable"
    )

    mcp_states = components.mcp_manager.get_server_states()
    mcp_summary = {
        "healthy": sum(1 for item in mcp_states.values() if item.get("healthy")),
        "configured": sum(1 for item in mcp_states.values() if item.get("configured")),
        "total": len(mcp_states),
        "errors": {
            name: item.get("last_error")
            for name, item in mcp_states.items()
            if item.get("enabled")
            and item.get("configured")
            and not item.get("healthy")
        },
    }
    tool_name_collisions = {
        name: item.get("tool_name_collisions")
        for name, item in mcp_states.items()
        if item.get("tool_name_collisions")
    }
    if tool_name_collisions:
        mcp_summary["tool_name_collisions"] = tool_name_collisions

    snapshot_summary = _probe_data_snapshots(settings)

    corpus_probe, run_execution_probe, background_jobs_probe = await asyncio.gather(
        _probe_knowledge_corpus(),
        _probe_run_execution(components),
        _probe_background_jobs(components),
    )

    components_status = {
        "database": {"ready": db_ok, "message": db_message},
        "redis": {"ready": redis_ok, "message": redis_message},
        "models": {"ready": model_ok, "message": model_message},
        "checkpointer": {"ready": checkpointer_ok, "message": checkpointer_message},
        "mcp": {"ready": True, **mcp_summary},
        "data_snapshots": snapshot_summary,
        "knowledge_corpus": corpus_probe,
        "database_schema": _probe_schema_report(components),
        "run_execution": run_execution_probe,
        "background_jobs": background_jobs_probe,
        "optional_capabilities": capability_report(settings),
        "resource_limits": _probe_resource_limits(settings),
        "pdf_export": _probe_pdf_export(),
    }
    ready = all(
        component["ready"]
        for name, component in components_status.items()
        if name not in _NON_BLOCKING_COMPONENTS
    )
    return {
        "status": "ready" if ready else "not_ready",
        "components": components_status,
    }
