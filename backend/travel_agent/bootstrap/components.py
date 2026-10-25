from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from travel_agent.conversation.workflow import FastAnswerWorkflow
from travel_agent.integrations.weather import default_weather_providers
from travel_agent.knowledge.indexer import KnowledgeIndexer
from travel_agent.knowledge.retriever import HybridRetriever
from travel_agent.llm.router import ModelRouter, get_model_router
from travel_agent.llm.usage import UsageRecorder, get_usage_recorder
from travel_agent.memory.chat_session import ChatSessionMemory
from travel_agent.memory.memory_extractor import MemoryExtractor
from travel_agent.memory.user_profile import UserProfileMemory
from travel_agent.planning.weather.context_builder import WeatherContextBuilder
from travel_agent.planning.workflow import TravelPlanningWorkflow
from travel_agent.runtime.background_jobs import BackgroundJobWorker
from travel_agent.runtime.run_recovery import RunRecoveryService
from travel_agent.runtime.usage_flush import UsageFlushService
from travel_agent.storage.background_job_store import (
    BackgroundJobStore,
    get_background_job_store,
)
from travel_agent.storage.cost_ledger_store import (
    CostLedgerStore,
    get_cost_ledger_store,
)
from travel_agent.storage.delivery_bundle_store import DeliveryBundleStore
from travel_agent.storage.maintenance.report import SchemaReport
from travel_agent.storage.memory_lifecycle_store import (
    MemoryLifecycleStore,
    get_memory_lifecycle_store,
)
from travel_agent.storage.preset_store import PresetStore
from travel_agent.storage.product_configuration_store import ProductConfigurationStore
from travel_agent.storage.provider_snapshot_cache import (
    ProviderSnapshotCache,
    get_provider_snapshot_cache,
)
from travel_agent.storage.run_command_store import (
    RunCommandStore,
    get_run_command_store,
)
from travel_agent.storage.run_execution_store import (
    RunExecutionStore,
    get_run_execution_store,
)
from travel_agent.storage.tool_audit_store import ToolAuditStore, get_tool_audit_store
from travel_agent.storage.trip_run_store import TripRunStore, get_trip_run_store
from travel_agent.storage.worker_journal_store import WorkerJournalStore
from travel_agent.tools.mcp_manager import MCPManager, get_mcp_manager
from travel_agent.tools.registry import ToolRegistry, get_tool_registry


@dataclass
class AppComponents:
    """全量组件容器，应用启动时构建一次"""

    schema_report: Optional[SchemaReport] = None

    model_router: ModelRouter = field(default_factory=get_model_router)

    usage_recorder: UsageRecorder = field(default_factory=get_usage_recorder)
    usage_flush_service: Optional[UsageFlushService] = None

    cost_ledger_store: CostLedgerStore = field(default_factory=get_cost_ledger_store)

    chat_session_memory: ChatSessionMemory = field(default_factory=ChatSessionMemory)
    user_profile_memory: UserProfileMemory = field(default_factory=UserProfileMemory)

    memory_extractor: MemoryExtractor = field(default_factory=MemoryExtractor)

    knowledge_indexer: KnowledgeIndexer = field(default_factory=KnowledgeIndexer)
    vector_retriever: HybridRetriever = field(default_factory=HybridRetriever)

    tool_registry: ToolRegistry = field(default_factory=get_tool_registry)
    mcp_manager: MCPManager = field(default_factory=get_mcp_manager)
    provider_snapshot_cache: ProviderSnapshotCache = field(
        default_factory=get_provider_snapshot_cache
    )

    checkpointer: Optional[Any] = None
    _checkpointer_pool: Optional[Any] = None
    checkpointer_available: bool = False
    checkpointer_init_error: Optional[str] = None
    travel_workflow: TravelPlanningWorkflow = field(
        default_factory=TravelPlanningWorkflow
    )
    fast_workflow: FastAnswerWorkflow = field(default_factory=FastAnswerWorkflow)

    preset_store: PresetStore = field(default_factory=PresetStore)
    product_configuration_store: ProductConfigurationStore = field(
        default_factory=ProductConfigurationStore
    )

    trip_run_store: TripRunStore = field(default_factory=get_trip_run_store)

    run_execution_store: RunExecutionStore = field(
        default_factory=get_run_execution_store
    )
    run_command_store: RunCommandStore = field(default_factory=get_run_command_store)
    run_recovery_service: Optional[RunRecoveryService] = None

    background_job_store: BackgroundJobStore = field(
        default_factory=get_background_job_store
    )
    background_job_worker: Optional[BackgroundJobWorker] = None

    delivery_bundle_store: DeliveryBundleStore = field(
        default_factory=DeliveryBundleStore
    )
    weather_context_builder: WeatherContextBuilder = field(
        default_factory=lambda: WeatherContextBuilder(default_weather_providers())
    )
    weather_refresh_clock: Optional[Any] = None

    tool_audit_store: ToolAuditStore = field(default_factory=get_tool_audit_store)
    worker_journal_store: WorkerJournalStore = field(default_factory=WorkerJournalStore)

    memory_lifecycle_store: MemoryLifecycleStore = field(
        default_factory=get_memory_lifecycle_store
    )
