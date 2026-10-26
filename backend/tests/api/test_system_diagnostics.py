"""真实 readiness 组合逻辑，依赖项的 I/O 用假实现。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from travel_agent.api.app import create_app
from travel_agent.bootstrap import registry
from travel_agent.bootstrap.diagnostics import dependencies
from travel_agent.config.models import Settings
from travel_agent.config import loader
from travel_agent.integrations import pdf_readiness
from travel_agent.storage import database, redis_client
from travel_agent.storage.maintenance.report import SchemaReport


@pytest.fixture
def diagnostic_runtime(monkeypatch):
    settings = Settings(embedding={"enabled": False})
    monkeypatch.setattr(loader, "_effective", SimpleNamespace(settings=settings))
    monkeypatch.setattr(registry, "_components", None)
    monkeypatch.setattr(
        pdf_readiness,
        "_last_probe",
        pdf_readiness.PdfRendererProbe(
            available=False, problem="fixture font unavailable"
        ),
    )
    events = []

    async def execute(sql):
        assert str(sql) == "SELECT 1"
        events.append("database")

    @asynccontextmanager
    async def connection():
        yield SimpleNamespace(execute=execute)

    monkeypatch.setattr(
        database, "get_engine", lambda: SimpleNamespace(connect=connection)
    )

    async def ping():
        events.append("redis")

    monkeypatch.setattr(redis_client, "get_redis", lambda: SimpleNamespace(ping=ping))
    router = SimpleNamespace(
        get_primary=lambda: events.append("primary"),
        get_fast=lambda: events.append("fast"),
    )
    monkeypatch.setattr(dependencies, "get_model_router", lambda: router)
    components = SimpleNamespace(
        schema_report=SchemaReport(reachable=True, revision="fixture"),
        checkpointer=object(),
        tool_registry=SimpleNamespace(count=7),
        mcp_manager=SimpleNamespace(
            get_server_states=lambda: {
                "fixture": {
                    "name": "fixture",
                    "enabled": True,
                    "healthy": False,
                    "configured": True,
                    "last_error": "fixture offline",
                }
            }
        ),
        run_recovery_service=None,
        background_job_worker=None,
        run_execution_store=SimpleNamespace(
            count_active_leases=AsyncMock(
                side_effect=RuntimeError("fixture leases unavailable")
            )
        ),
        run_command_store=SimpleNamespace(
            count_open_by_type=AsyncMock(
                side_effect=RuntimeError("fixture commands unavailable")
            )
        ),
        background_job_store=SimpleNamespace(
            counts_by_type_status=AsyncMock(
                side_effect=RuntimeError("fixture jobs unavailable")
            ),
            oldest_pending_seconds=AsyncMock(),
        ),
    )
    registry.set_components(components)
    return SimpleNamespace(settings=settings, components=components, events=events)


def client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://offline.test"
    )


async def test_nonblocking_health_failures_keep_service_ready(diagnostic_runtime):
    async with client() as api:
        response = await api.get("/api/health/ready")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    c = payload["components"]
    assert c["knowledge_corpus"]["ready"] is False
    assert c["knowledge_corpus"]["enabled"] is False
    assert c["pdf_export"]["available"] is False
    assert c["mcp"]["errors"] == {"fixture": "fixture offline"}
    assert c["run_execution"]["active_leases"] is None
    assert c["run_execution"]["pending_commands"] is None
    assert c["background_jobs"]["counts"] is None
    assert c["database_schema"]["ready"] is True
    assert diagnostic_runtime.events == ["database", "redis", "primary", "fast"]


@pytest.mark.parametrize(
    "schema", [None, SchemaReport(reachable=True, problems=["fixture incompatible"])]
)
async def test_missing_or_incompatible_schema_blocks_readiness(
    diagnostic_runtime, schema
):
    diagnostic_runtime.components.schema_report = schema
    async with client() as api:
        response = await api.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["components"]["database_schema"]["ready"] is False


@pytest.mark.parametrize(
    "gates,checkpoint,status",
    [(False, None, 200), (True, None, 503), (True, False, 503), (True, object(), 200)],
)
async def test_checkpointer_truthiness_and_gate_policy(
    diagnostic_runtime, gates, checkpoint, status
):
    diagnostic_runtime.settings.run_control.plan_gate_enabled = gates
    diagnostic_runtime.components.checkpointer = checkpoint
    async with client() as api:
        response = await api.get("/api/health/ready")
    assert response.status_code == status
    assert response.json()["components"]["checkpointer"]["ready"] is (status == 200)


@pytest.mark.parametrize("dependency", ["database", "redis", "models"])
async def test_dependency_failures_block_readiness(
    diagnostic_runtime, monkeypatch, dependency
):
    def fail(*args):
        raise RuntimeError("fixture dependency unavailable")

    if dependency == "database":
        monkeypatch.setattr(database, "get_engine", fail)
    elif dependency == "redis":
        monkeypatch.setattr(redis_client, "get_redis", fail)
    else:
        monkeypatch.setattr(dependencies, "get_model_router", fail)
    async with client() as api:
        response = await api.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json()["components"][dependency] == {
        "ready": False,
        "message": "fixture dependency unavailable",
    }


async def test_optional_capability_mismatch_blocks_readiness(
    diagnostic_runtime, monkeypatch
):
    from travel_agent.config import capabilities

    diagnostic_runtime.settings.embedding.enabled = True
    diagnostic_runtime.settings.embedding.provider = "qwen3"
    find_spec = capabilities.importlib.util.find_spec
    monkeypatch.setattr(
        capabilities.importlib.util,
        "find_spec",
        lambda name: (
            None
            if name in {"onnxruntime", "tokenizers", "huggingface_hub", "numpy"}
            else find_spec(name)
        ),
    )
    from travel_agent.knowledge import factory_seed

    monkeypatch.setattr(
        factory_seed,
        "factory_collection_counts",
        AsyncMock(side_effect=RuntimeError("fixture corpus offline")),
    )
    async with client() as api:
        response = await api.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json()["components"]["optional_capabilities"]["ready"] is False


async def test_status_is_an_api_schema_projection(diagnostic_runtime):
    async with client() as api:
        response = await api.get("/api/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "running"
    assert payload["tools_count"] == 7
    assert payload["db_connected"] is True
    assert payload["redis_connected"] is True
    assert "memory_extraction" in payload
    assert diagnostic_runtime.events == ["database", "redis"]
