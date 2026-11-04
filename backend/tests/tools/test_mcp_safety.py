from __future__ import annotations

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
