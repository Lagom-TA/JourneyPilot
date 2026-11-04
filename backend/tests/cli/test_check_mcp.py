"""MCP 探测退出时关闭已经打开的会话。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from scripts import check_mcp


async def test_probe_timeout_closes_mcp_sessions(monkeypatch):
    async def initialize(_servers):
        await asyncio.Event().wait()

    manager = SimpleNamespace(initialize=initialize, close_all_sessions=AsyncMock())
    monkeypatch.setattr(check_mcp, "reload_settings", lambda: SimpleNamespace(mcp_servers={}))
    monkeypatch.setattr(check_mcp, "MCPManager", lambda: manager)
    monkeypatch.setenv("MCP_CHECK_TIMEOUT_SECONDS", "0")
    assert await check_mcp.main() == 1
    manager.close_all_sessions.assert_awaited_once()
