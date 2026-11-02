"""探测已配置的 MCP server 是否可用。

用法：

    python backend/scripts/check_mcp.py

按当前 ``config.yaml`` 初始化 MCPManager，逐个打印 server 的 status、工具数与类型；
启用的 server 不健康时返回 1，全部健康返回 0。``MCP_CHECK_TIMEOUT_SECONDS`` 可覆盖
整体探测超时（默认 45 秒）。脚本不访问数据库、不调用模型，只在本机孵化 MCP 进程。
诊断数据库/架构问题请用 ``journeypilot doctor``。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from travel_agent.config.loader import reload_settings  # noqa: E402
from travel_agent.tools.mcp_manager import MCPManager  # noqa: E402


async def main() -> int:
    settings = reload_settings()
    manager = MCPManager()
    timeout = int(os.getenv("MCP_CHECK_TIMEOUT_SECONDS", "45"))
    try:
        states = await asyncio.wait_for(manager.initialize(settings.mcp_servers), timeout=timeout)
    except asyncio.TimeoutError:
        print(f"MCP probe timed out after {timeout}s")
        return 1

    print("MCP probe results:")
    print("-" * 80)

    failed = []
    for name, state in states.items():
        line = (
            f"{name:<16} status={state['status']:<14} "
            f"tools={state['tool_count']:<3} type={state['type']:<5}"
        )
        if state.get("last_error"):
            line += f" error={state['last_error']}"
        print(line)
        if state["enabled"] and state["status"] != "healthy":
            failed.append((name, state["status"]))

    print("-" * 80)
    if failed:
        print("Unhealthy enabled MCP servers:")
        for name, status in failed:
            print(f"- {name}: {status}")
        return 1

    print("All enabled MCP servers are healthy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
