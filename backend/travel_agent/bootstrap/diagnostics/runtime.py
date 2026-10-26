"""执行状态、任务积压与资源诊断。"""

from __future__ import annotations

from typing import Any, Dict


async def _probe_run_execution(components: Any) -> Dict[str, Any]:
    """单个 Run 失败或无法恢复不影响接收其他任务。"""

    recovery = components.run_recovery_service
    report = recovery.last_report if recovery is not None else None
    payload: Dict[str, Any] = {
        "ready": True,
        "sweeper_running": recovery is not None,
        "recovered_run_count": len(report.outcomes) if report else 0,
        "resume_available": report.resume_available_count if report else 0,
        "recovery_counts": report.counts if report else {},
        "recovery_failures": list(report.failures) if report else [],
    }
    try:
        payload[
            "active_leases"
        ] = await components.run_execution_store.count_active_leases()
    except Exception as exc:
        payload["active_leases"] = None
        payload["message"] = f"执行租约计数失败: {exc}"
    try:
        payload[
            "pending_commands"
        ] = await components.run_command_store.count_open_by_type()
    except Exception as exc:
        payload["pending_commands"] = None
        payload["command_message"] = f"控制命令计数失败: {exc}"
    return payload


async def _probe_background_jobs(components: Any) -> Dict[str, Any]:
    """记忆抽取失败只展示计数，不阻断问答就绪。"""

    worker = components.background_job_worker
    payload: Dict[str, Any] = {"ready": True, "worker_running": worker is not None}
    try:
        payload[
            "counts"
        ] = await components.background_job_store.counts_by_type_status()
        payload[
            "oldest_pending_seconds"
        ] = await components.background_job_store.oldest_pending_seconds()
    except Exception as exc:
        payload["counts"] = None
        payload["message"] = f"后台任务计数失败: {exc}"
    return payload


def _probe_resource_limits(settings: Any) -> Dict[str, Any]:
    """单个资源通道饱和不阻断整个服务。"""

    from travel_agent.runtime.blocking_work import blocking_work_metrics
    from travel_agent.runtime.concurrency import channel_metrics

    channels = channel_metrics()
    return {
        "ready": True,
        "blocking_work": blocking_work_metrics(),
        "provider_channels": {
            name.removeprefix("llm."): metrics
            for name, metrics in channels.items()
            if not name.startswith("blocking.")
        },
        "run_budget": settings.run_budget.model_dump(mode="json"),
        "ingest": settings.ingest.model_dump(mode="json"),
    }
