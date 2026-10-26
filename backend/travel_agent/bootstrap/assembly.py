from __future__ import annotations

import logging
from typing import Optional

from travel_agent.bootstrap.components import AppComponents
from travel_agent.bootstrap.jobs import build_job_handlers
from travel_agent.config.models import Settings
from travel_agent.config.loader import get_settings
from travel_agent.conversation.workflow import FastAnswerWorkflow
from travel_agent.integrations.weather import default_weather_providers
from travel_agent.knowledge.indexer import KnowledgeIndexer
from travel_agent.knowledge.retriever import HybridRetriever
from travel_agent.llm.router import get_model_router
from travel_agent.llm.usage import get_usage_recorder
from travel_agent.memory.chat_session import ChatSessionMemory
from travel_agent.memory.memory_extractor import MemoryExtractor
from travel_agent.memory.user_profile import UserProfileMemory
from travel_agent.planning.weather.context_builder import WeatherContextBuilder
from travel_agent.planning.workflow import TravelPlanningWorkflow
from travel_agent.runtime.background_jobs import BackgroundJobWorker
from travel_agent.runtime.run_recovery import RunRecoveryService
from travel_agent.runtime.usage_flush import UsageFlushService
from travel_agent.storage.background_job_store import get_background_job_store
from travel_agent.storage.cost_ledger_store import get_cost_ledger_store
from travel_agent.storage.delivery_bundle_store import DeliveryBundleStore
from travel_agent.storage.maintenance.report import verify_database_contract
from travel_agent.storage.memory_lifecycle_store import get_memory_lifecycle_store
from travel_agent.storage.preset_store import PresetStore
from travel_agent.storage.product_configuration_store import ProductConfigurationStore
from travel_agent.storage.provider_snapshot_cache import get_provider_snapshot_cache
from travel_agent.storage.run_command_store import get_run_command_store
from travel_agent.storage.run_execution_store import get_run_execution_store
from travel_agent.storage.tool_audit_store import get_tool_audit_store
from travel_agent.storage.trip_run_store import get_trip_run_store
from travel_agent.tools.mcp_manager import get_mcp_manager
from travel_agent.tools.registry import get_tool_registry

logger = logging.getLogger(__name__)


async def build_components(settings: Optional[Settings] = None) -> AppComponents:
    """按使用方的依赖顺序构建全部组件。"""
    settings = settings or get_settings()
    logger.info(f"构建应用组件（环境: {settings.env}）")

    from travel_agent.storage.database import get_engine

    schema_report = await verify_database_contract(
        get_engine(), embedding_dimensions=settings.embedding.dimensions
    )
    schema_report.log_summary()

    checkpointer = None
    checkpointer_pool = None
    checkpointer_available = False
    checkpointer_init_error: Optional[str] = None
    require_checkpointer = bool(
        getattr(settings.checkpoint_retention, "require_on_startup", False)
    )
    try:
        from travel_agent.storage.checkpointer import build_checkpointer

        checkpointer, checkpointer_pool = await build_checkpointer(settings)
        checkpointer_available = checkpointer is not None
    except Exception as e:
        checkpointer_init_error = f"{type(e).__name__}: {e}"
        if require_checkpointer:
            logger.error(
                "LangGraph checkpointer 初始化失败且 require_on_startup=true，拒绝启动: %s",
                e,
            )
            raise RuntimeError(
                "checkpointer required but initialization failed: "
                f"{checkpointer_init_error}"
            ) from e
        logger.error(
            "LangGraph checkpointer 初始化失败（将使用无持久图执行；"
            "plan_gate/crash-resume 不可用）: %s",
            e,
        )

    try:
        from travel_agent.tools.builtin_tools import register_builtin_tools

        register_builtin_tools()
        logger.info("内置工具注册完成")
    except Exception as e:
        logger.warning(f"内置工具注册失败: {e}")

    mcp_manager = get_mcp_manager()
    try:
        await mcp_manager.initialize(settings.mcp_servers)
    except Exception as e:
        logger.warning(f"MCP 工具初始化失败（部分工具不可用）: {e}")

    trip_run_store = get_trip_run_store()
    delivery_bundle_store = DeliveryBundleStore()
    weather_context_builder = WeatherContextBuilder(default_weather_providers())
    travel_workflow = TravelPlanningWorkflow(
        checkpointer=checkpointer,
        delivery_bundle_store=delivery_bundle_store,
        trip_run_store=trip_run_store,
    )
    run_execution_store = get_run_execution_store()
    run_command_store = get_run_command_store()

    async def _delivery_bundle_persisted(run_id: str) -> bool:
        """恢复判定用的持久化产物探针：该 run 是否留下过 durable Bundle。"""

        return await delivery_bundle_store.get_current_bundle_id(run_id) is not None

    run_recovery_service = RunRecoveryService(
        trip_run_store=trip_run_store,
        execution_store=run_execution_store,
        command_store=run_command_store,
        checkpoint_probe=travel_workflow.has_checkpoint
        if checkpointer_available
        else None,
        bundle_probe=_delivery_bundle_persisted,
        sweep_seconds=settings.run_control.recovery_sweep_seconds,
    )
    background_job_store = get_background_job_store()
    components = AppComponents(
        schema_report=schema_report,
        model_router=get_model_router(),
        usage_recorder=get_usage_recorder(),
        cost_ledger_store=get_cost_ledger_store(),
        chat_session_memory=ChatSessionMemory(),
        user_profile_memory=UserProfileMemory(),
        memory_extractor=MemoryExtractor(),
        knowledge_indexer=KnowledgeIndexer(),
        vector_retriever=HybridRetriever(),
        tool_registry=get_tool_registry(),
        mcp_manager=mcp_manager,
        provider_snapshot_cache=get_provider_snapshot_cache(),
        checkpointer=checkpointer,
        _checkpointer_pool=checkpointer_pool,
        checkpointer_available=checkpointer_available,
        checkpointer_init_error=checkpointer_init_error,
        travel_workflow=travel_workflow,
        fast_workflow=FastAnswerWorkflow(),
        preset_store=PresetStore(),
        product_configuration_store=ProductConfigurationStore(),
        trip_run_store=trip_run_store,
        run_execution_store=run_execution_store,
        run_command_store=run_command_store,
        run_recovery_service=run_recovery_service,
        background_job_store=background_job_store,
        delivery_bundle_store=delivery_bundle_store,
        weather_context_builder=weather_context_builder,
        tool_audit_store=get_tool_audit_store(),
        memory_lifecycle_store=get_memory_lifecycle_store(),
    )
    if settings.embedding.enabled:
        components.background_job_worker = BackgroundJobWorker(
            background_job_store,
            build_job_handlers(components),
            poll_seconds=settings.background_jobs.poll_seconds,
            lease_seconds=settings.background_jobs.lease_seconds,
            batch_size=settings.background_jobs.batch_size,
            completed_retention_days=settings.background_jobs.completed_retention_days,
        )
    components.usage_flush_service = UsageFlushService(
        components.usage_recorder,
        components.cost_ledger_store,
        settings.usage.flush_seconds,
    )
    components.usage_flush_service.start()
    return components
