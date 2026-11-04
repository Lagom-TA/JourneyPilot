"""MCP defaults 的真实运行时行为。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from travel_agent.config import mcp_defaults
from travel_agent.config.mcp_defaults import default_mcp_servers
from travel_agent.config.models import MCPServerItem

_EXPECTED_KEYS = {
    "tavily-search",
    "brave-search",
    "firecrawl",
    "duckduckgo-search",
    "fetch",
    "baidu-maps",
    "amap-maps",
    "duffel-flights",
    "12306-train",
    "open-meteo",
    "currency-exchange-mcp",
}


def _force_local_bins(monkeypatch: pytest.MonkeyPatch, *, present: bool) -> None:
    bin_dir = mcp_defaults._MCP_DIR / "node_modules" / ".bin"
    real_exists = Path.exists

    def fake_exists(path: Path) -> bool:
        if path.parent == bin_dir:
            return present
        return real_exists(path)

    monkeypatch.setattr(Path, "exists", fake_exists)


def test_defaults_expose_real_servers_and_launch_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "TAVILY_API_KEY",
        "BRAVE_API_KEY",
        "FIRECRAWL_API_KEY",
        "BAIDU_MAP_API_KEY",
        "AMAP_MAPS_API_KEY",
        "DUFFEL_API_KEY_LIVE",
    ):
        monkeypatch.delenv(name, raising=False)
    _force_local_bins(monkeypatch, present=False)

    servers = default_mcp_servers(MCPServerItem)

    assert set(servers) == _EXPECTED_KEYS
    assert servers["tavily-search"].command.endswith("node_modules/.bin/tavily-mcp")
    assert servers["tavily-search"].args == []
    assert servers["duckduckgo-search"].command == sys.executable
    assert servers["duckduckgo-search"].args[0].endswith("backend/mcp/search/free_search.py")
    assert servers["fetch"].args == ["-m", "mcp_server_fetch"]
    assert servers["tavily-search"].required_env == ["TAVILY_API_KEY"]
    assert servers["open-meteo"].disabled is True


def test_node_servers_require_the_locked_local_bin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_local_bins(monkeypatch, present=True)
    local = default_mcp_servers(MCPServerItem)["tavily-search"]
    assert local.command.endswith("node_modules/.bin/tavily-mcp")
    assert local.args == []

    _force_local_bins(monkeypatch, present=False)
    missing = default_mcp_servers(MCPServerItem)["tavily-search"]
    assert missing.command == local.command
    assert missing.args == []


def test_open_meteo_mcp_requires_explicit_enablement():
    from travel_agent.config.loader import build_settings

    assert build_settings({}).mcp_servers["open-meteo"].disabled is True
    settings = build_settings({"mcp": {"servers": {"open-meteo": {"disabled": False}}}})
    assert settings.mcp_servers["open-meteo"].disabled is False


def test_provider_env_is_fresh_and_limited_to_required_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    _force_local_bins(monkeypatch, present=False)
    first = default_mcp_servers(MCPServerItem)
    assert first["tavily-search"].env == {}
    assert first["duckduckgo-search"].env is None

    monkeypatch.setenv("TAVILY_API_KEY", "set-later")
    second = default_mcp_servers(MCPServerItem)
    assert second["tavily-search"].env == {"TAVILY_API_KEY": "set-later"}
    assert first["tavily-search"].env == {}
    assert all(set(item.env or {}) <= set(item.required_env) for item in second.values())
