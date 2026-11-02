"""stdio MCP server 只拿到运行所需环境与自己的显式配置。"""

from __future__ import annotations

from travel_agent.tools.mcp_manager import _stdio_environment


def test_stdio_environment_drops_service_credentials(monkeypatch):
    monkeys = {
        "PATH": "/usr/bin",
        "HOME": "/home/tester",
        "LANG": "zh_CN.UTF-8",
        "JOURNEYPILOT_DATABASE__PASSWORD": "db-secret",
        "OPENAI_API_KEY": "model-secret",
        "DUFFEL_API_KEY_LIVE": "flight-secret",
        "UNRELATED": "value",
    }
    for key, value in monkeys.items():
        monkeypatch.setenv(key, value)
    env = _stdio_environment({"TAVILY_API_KEY": "tavily-secret"})
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/home/tester"
    assert env["LANG"] == "zh_CN.UTF-8"
    assert env["TAVILY_API_KEY"] == "tavily-secret"
    for key in monkeys:
        if key not in {"PATH", "HOME", "LANG"}:
            assert key not in env
