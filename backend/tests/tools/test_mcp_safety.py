from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from travel_agent.api.routes.system import get_mcp_servers
from travel_agent.bootstrap import registry as component_registry
from travel_agent.bootstrap.diagnostics.readiness import collect_readiness
from travel_agent.config import loader
from travel_agent.config.models import MCPServerItem, Settings
from travel_agent.tools import execution, mcp_manager
from travel_agent.tools.mcp_manager import MCPManager, MCPServerState
from travel_agent.tools.registry import ToolRegistry


async def test_parallel_mcp_discovery_registers_collisions_in_config_order(monkeypatch):
    from travel_agent.tools import registry as registry_module

    registry = ToolRegistry()
    monkeypatch.setattr(registry_module, "_registry", registry)
    manager = MCPManager()
    first_started, second_finished = asyncio.Event(), asyncio.Event()

    async def discover(name, _config):
        if name == "first":
            first_started.set()
            await second_finished.wait()
        else:
            await first_started.wait()
            second_finished.set()
        return [{"name": "shared", "description": name, "inputSchema": {"type": "object"}}]

    monkeypatch.setattr(manager, "_list_server_tools", discover)
    states = await manager.initialize({
        "first": MCPServerItem(command="first"),
        "second": MCPServerItem(command="second"),
    })
    assert registry.get_tool_metadata("shared")["server_name"] == "first"
    assert states["first"]["tools_list"] == ["shared"]
    assert states["second"]["tools_list"] == []
    assert states["second"]["tool_name_collisions"] == ["shared"]


async def test_uninstalled_node_program_is_reported_without_starting_it(monkeypatch, tmp_path, caplog):
    import sys

    from travel_agent.tools import registry as registry_module

    monkeypatch.setattr(registry_module, "_registry", ToolRegistry())
    manager = MCPManager()
    probe = AsyncMock(return_value=[])
    monkeypatch.setattr(manager, "_list_server_tools", probe)
    absent = tmp_path / "node_modules" / ".bin" / "tavily-mcp"

    with caplog.at_level(logging.WARNING, logger="travel_agent.tools.mcp_manager"):
        states = await manager.initialize({
            "node-service": MCPServerItem(command=str(absent)),
            "installed": MCPServerItem(command=sys.executable),
        })

    assert [call.args[0] for call in probe.call_args_list] == ["installed"]
    assert states["node-service"]["status"] == "misconfigured"
    assert "npm ci" in states["node-service"]["last_error"]
    assert str(tmp_path) not in states["node-service"]["last_error"]
    assert any(str(absent) in record.getMessage() for record in caplog.records)
    assert states["installed"]["status"] == "healthy"


@pytest.mark.parametrize(
    ("raw", "reason", "retryable"),
    [
        ("HTTP 503 https://private.example/?key=secret", "HTTP 503", True),
        ("HTTP 401 https://private.example/?key=secret", "HTTP 401", False),
        ("timeout: https://private.example/?key=secret", "timeout", True),
        ("CUQPS_HAS_EXCEEDED_THE_LIMIT https://private.example/?key=secret", "rate limit", True),
        ("quota exceeded https://private.example/?key=secret", "quota", False),
        ("amap refused: INVALID_USER_KEY (10001) https://private.example/?key=secret", "authentication", False),
        ("Input validation error: {'secret': 'private'}", "invalid parameter", False),
        ("Duffel returned no complete one-way routes", "no results", False),
    ],
)
def test_mcp_failure_keeps_safe_reason_and_retry_decision(raw, reason, retryable):
    result = mcp_manager._safe_mcp_error(raw)
    assert result.startswith(reason)
    assert execution._is_retryable_tool_error(result) is retryable
    assert "private.example" not in result
    assert "secret" not in result


async def test_stdio_server_receives_allowlisted_and_explicit_environment(monkeypatch):
    parent_env = {
        "PATH": "/test/bin",
        "HOME": "/test/home",
        "LANG": "en_US.UTF-8",
        "HTTPS_PROXY": "http://proxy.example",
        "SERVICE_KEY": "ambient-service-key",
        "JOURNEYPILOT_PRIMARY_MODEL__API_KEY": "private-model-key",
        "JOURNEYPILOT_DATABASE__PASSWORD": "private-db-password",
        "OTHER_SERVICE_API_KEY": "other-service-key",
        "UNRELATED": "unrelated-value",
    }
    monkeypatch.setattr(mcp_manager, "os", SimpleNamespace(environ=parent_env))
    observed = {}

    @asynccontextmanager
    async def stdio(parameters):
        observed.update(parameters.env)
        yield object(), object()

    class Session:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(mcp_manager, "stdio_client", stdio)
    monkeypatch.setattr(mcp_manager, "_OutputSchemaTolerantSession", Session)
    server = MCPServerItem(command="mcp-server", env={"SERVICE_KEY": "service-key"})
    async with MCPManager()._open_session("service", server):
        pass

    assert observed == {
        "PATH": "/test/bin",
        "HOME": "/test/home",
        "LANG": "en_US.UTF-8",
        "HTTPS_PROXY": "http://proxy.example",
        "SERVICE_KEY": "service-key",
    }


async def test_reused_mcp_session_closes_in_its_owner_task(monkeypatch):
    events = []

    class Session:
        async def initialize(self):
            events.append("initialized")

        def take_output_schema_violation(self):
            return None

        async def call_tool(self, name, arguments):
            events.append(name)
            return {"content": [{"type": "text", "text": "ok"}]}

    @asynccontextmanager
    async def open_session(_name, _config):
        owner = asyncio.current_task()
        events.append("opened")
        try:
            yield Session()
        finally:
            assert asyncio.current_task() is owner
            events.append("closed")

    manager = MCPManager()
    manager._server_configs["fixture"] = MCPServerItem(command="fixture")
    monkeypatch.setattr(manager, "_open_session", open_session)

    assert (await manager._execute_tool("fixture", "first", {}))["success"]
    assert (await manager._execute_tool("fixture", "second", {}))["success"]
    await manager.close_all_sessions()

    assert events == ["opened", "initialized", "first", "second", "closed"]
    assert not manager._session_leases


async def test_cancelled_mcp_call_closes_its_session(monkeypatch):
    started = asyncio.Event()
    closed = asyncio.Event()

    class Session:
        async def initialize(self):
            pass

        def take_output_schema_violation(self):
            return None

        async def call_tool(self, _name, _arguments):
            started.set()
            await asyncio.Event().wait()

    @asynccontextmanager
    async def open_session(_name, _config):
        try:
            yield Session()
        finally:
            closed.set()

    manager = MCPManager()
    manager._server_configs["fixture"] = MCPServerItem(command="fixture")
    monkeypatch.setattr(manager, "_open_session", open_session)

    call = asyncio.create_task(manager._execute_tool("fixture", "wait", {}))
    await started.wait()
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    assert closed.is_set()
    assert not manager._session_leases


async def test_mcp_shutdown_waits_for_inflight_session_open(monkeypatch):
    opening = asyncio.Event()
    proceed = asyncio.Event()
    closed = asyncio.Event()

    class Session:
        async def initialize(self):
            pass

        def take_output_schema_violation(self):
            return None

        async def call_tool(self, _name, _arguments):
            return {"content": [{"type": "text", "text": "ok"}]}

    @asynccontextmanager
    async def open_session(_name, _config):
        opening.set()
        await proceed.wait()
        try:
            yield Session()
        finally:
            closed.set()

    manager = MCPManager()
    manager._server_configs["fixture"] = MCPServerItem(command="fixture")
    monkeypatch.setattr(manager, "_open_session", open_session)

    call = asyncio.create_task(manager._execute_tool("fixture", "call", {}))
    await opening.wait()
    shutdown = asyncio.create_task(manager.close_all_sessions())
    await asyncio.sleep(0)
    assert not shutdown.done()
    proceed.set()
    assert (await call)["success"]
    await shutdown
    assert closed.is_set()
    assert not manager._session_leases


async def test_cancelled_mcp_session_owner_is_reopened_on_next_call(monkeypatch):
    events = []

    class Session:
        async def initialize(self):
            pass

        def take_output_schema_violation(self):
            return None

        async def call_tool(self, _name, _arguments):
            return {"content": [{"type": "text", "text": "ok"}]}

    @asynccontextmanager
    async def open_session(_name, _config):
        events.append("opened")
        try:
            yield Session()
        finally:
            events.append("closed")

    manager = MCPManager()
    manager._server_configs["fixture"] = MCPServerItem(command="fixture")
    monkeypatch.setattr(manager, "_open_session", open_session)

    assert (await manager._execute_tool("fixture", "call", {}))["success"]
    owner = manager._session_leases["fixture"].owner_task
    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner
    assert (await manager._execute_tool("fixture", "call", {}))["success"]
    await manager.close_all_sessions()
    assert events == ["opened", "closed", "opened", "closed"]


async def test_mcp_failure_is_safe_in_status_results_logs_and_audit(monkeypatch, caplog):
    secret = "private-credential-value"
    raw = f"HTTP 503 https://private.example/path?token={secret} /private/file"
    manager = MCPManager()
    server = MCPServerItem(command="mcp-server")

    async def failure(*_args, **_kwargs):
        raise RuntimeError(raw)

    monkeypatch.setattr(manager, "_list_server_tools", failure)
    with caplog.at_level(logging.ERROR):
        states = await manager.initialize({"fixture": server})

    assert states["fixture"]["last_error"] == "HTTP 503: MCP 服务请求失败"
    assert secret not in caplog.text
    assert "private.example" not in caplog.text

    monkeypatch.setattr(manager, "_acquire_session_lease", failure)
    registry = ToolRegistry()
    registry.register("fixture_tool", "fixture", {"type": "object"}, manager._make_executor("fixture", "fixture_tool"), source="mcp", server_name="fixture")
    monkeypatch.setattr(execution, "get_tool_registry", lambda: registry)
    records = []

    class Audit:
        async def record_envelope(self, envelope, **_kwargs):
            records.append(envelope)

    envelope = await execution.execute_tool(
        "fixture_tool", {}, allowed_tool_names={"fixture_tool"},
        max_retries=0, tool_audit_store=Audit(), allow_fallback=False,
    )
    assert envelope["status"] == "failed"
    assert envelope["error"] == "HTTP 503: MCP 服务请求失败"
    assert execution._is_retryable_tool_error(envelope["error"])
    assert records

    settings = Settings(embedding={"enabled": False})
    monkeypatch.setattr(loader, "_effective", SimpleNamespace(settings=settings))
    components = SimpleNamespace(mcp_manager=manager, checkpointer=None)
    monkeypatch.setattr(component_registry, "_components", components)
    monkeypatch.setattr("travel_agent.bootstrap.diagnostics.readiness._probe_database", AsyncMock(return_value=(True, "ok")))
    monkeypatch.setattr("travel_agent.bootstrap.diagnostics.readiness._probe_redis", AsyncMock(return_value=(True, "ok")))
    monkeypatch.setattr("travel_agent.bootstrap.diagnostics.readiness._probe_model_config", lambda: (True, "ok"))
    monkeypatch.setattr("travel_agent.bootstrap.diagnostics.readiness._probe_data_snapshots", lambda _settings: {})
    monkeypatch.setattr("travel_agent.bootstrap.diagnostics.readiness._probe_knowledge_corpus", AsyncMock(return_value={}))
    monkeypatch.setattr("travel_agent.bootstrap.diagnostics.readiness._probe_run_execution", AsyncMock(return_value={}))
    monkeypatch.setattr("travel_agent.bootstrap.diagnostics.readiness._probe_background_jobs", AsyncMock(return_value={}))
    monkeypatch.setattr("travel_agent.bootstrap.diagnostics.readiness._probe_schema_report", lambda _components: {"ready": True})
    monkeypatch.setattr("travel_agent.bootstrap.diagnostics.readiness._probe_resource_limits", lambda _settings: {})
    monkeypatch.setattr("travel_agent.bootstrap.diagnostics.readiness._probe_pdf_export", lambda: {})
    monkeypatch.setattr("travel_agent.bootstrap.diagnostics.readiness.capability_report", lambda _settings: {"ready": True})
    readiness = await collect_readiness()
    status = await get_mcp_servers()
    assert readiness["components"]["mcp"]["errors"]["fixture"] == envelope["error"]
    assert status["servers"][0]["last_error"] == envelope["error"]
    serialized = json.dumps([status, envelope, records, readiness], ensure_ascii=False)
    assert secret not in serialized
    assert "private.example" not in serialized
    assert "/private/file" not in serialized


async def test_protocol_and_amap_errors_do_not_return_provider_payload(monkeypatch):
    raw = "CUQPS https://private.example/?key=private-credential-value"

    class Session:
        def take_output_schema_violation(self):
            return None

        async def call_tool(self, _name, _arguments):
            return {"isError": True, "content": [{"text": raw}]}

    manager = MCPManager()
    manager._server_configs["amap-maps"] = MCPServerItem(command="mcp-server")
    manager._server_states["amap-maps"] = MCPServerState(name="amap-maps")
    monkeypatch.setattr(manager, "_acquire_session_lease", AsyncMock(return_value=SimpleNamespace(session=Session(), last_used_monotonic=0)))
    result = await manager._execute_tool("amap-maps", "maps_text_search", {})
    assert result["error"] == "rate limit: MCP 服务请求过于频繁"
    assert execution._is_retryable_tool_error(result["error"])
    assert "private-credential-value" not in json.dumps(result)
    assert "result" not in result

    refusal = mcp_manager._normalized_amap_place_result(
        "amap-maps", "maps_text_search", {"content": [{"text": raw}]}
    )
    assert refusal["error"] == result["error"]
    assert "private-credential-value" not in json.dumps(refusal)


async def test_currency_failure_keeps_status_without_response_body(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "mcp/currency/frankfurter_mcp.py"
    spec = importlib.util.spec_from_file_location("test_frankfurter_mcp", path)
    assert spec and spec.loader
    currency = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(currency)

    async def http_failure(_client, url):
        request = httpx.Request("GET", url)
        response = httpx.Response(503, request=request, text="private-credential-value")
        raise httpx.HTTPStatusError("private-credential-value", request=request, response=response)

    monkeypatch.setattr(currency, "_get_json", http_failure)
    with pytest.raises(RuntimeError, match="HTTP 503") as exc:
        await currency.call_tool(
            "latest_exchange_rates", {"base_currency": "USD", "to_currencies": "CNY"}
        )
    assert "private-credential-value" not in str(exc.value)
    assert execution._is_retryable_tool_error(mcp_manager._mcp_error_message(exc.value))


@pytest.mark.parametrize("tool_name,arguments", [
    ("convert_currency", {"amount": -1, "from_currency": "USD", "to_currency": "CNY"}),
    ("convert_currency", {"amount": "nan", "from_currency": "USD", "to_currency": "CNY"}),
    ("latest_exchange_rates", {"base_currency": "", "to_currencies": "CNY"}),
])
async def test_currency_invalid_arguments_are_mcp_errors(tool_name, arguments):
    path = Path(__file__).resolve().parents[2] / "mcp/currency/frankfurter_mcp.py"
    spec = importlib.util.spec_from_file_location("test_frankfurter_invalid", path)
    assert spec and spec.loader
    currency = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(currency)
    with pytest.raises(ValueError, match="invalid parameter"):
        await currency.call_tool(tool_name, arguments)
