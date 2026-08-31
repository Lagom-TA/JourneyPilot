"""JourneyPilot 内置 MCP server 配置。

这里直接维护仓库实际支持的 server 声明；只有依赖运行环境的部分留在求值阶段：
本地 Node bin 与 ``npx`` 的选择、仓内 Python 脚本路径、当前解释器以及 provider
原生环境变量。每次调用都会重新读取这些运行时值。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from .models import MCPServerItem

_REPO_ROOT = Path(__file__).resolve().parents[3]

# Keep this as data rather than another validation model. The configuration is owned by
# this module and is consumed only to build MCPServerItem instances at Settings creation.
# Insertion order is the server declaration order exposed by the API.
_DEFAULT_SERVERS: dict[str, dict[str, Any]] = {
    # Retrieval: agent-native search and deep fetch.
    "tavily-search": {
        "description": "Tavily agent 原生检索（搜索/提取/爬取，返回带引用结果，https://tavily.com）",
        "required_env": ("TAVILY_API_KEY",),
        "node": ("tavily-mcp@0.2.21", "tavily-mcp"),
    },
    "brave-search": {
        "description": "Brave 独立索引网络搜索（备份检索源，https://brave.com/search/api）",
        "required_env": ("BRAVE_API_KEY",),
        "node": ("@brave/brave-search-mcp-server@2.1.0", "brave-search-mcp-server"),
    },
    "firecrawl": {
        "description": "Firecrawl 深度网页抓取与正文提取（反爬强，https://firecrawl.dev）",
        "required_env": ("FIRECRAWL_API_KEY",),
        "node": ("firecrawl-mcp@3.23.0", "firecrawl-mcp"),
    },
    "duckduckgo-search": {
        "description": "DuckDuckGo 免费网络搜索（零 Key，作为降级兜底 free_web_search 的 backbone）",
        "python_script": "mcp_servers/search/free_search.py",
    },
    "fetch": {
        "description": "通用 HTTP 获取服务（零 Key 轻量抓取）",
        "python_module": "mcp_server_fetch",
    },
    # Maps: domestic Amap and Baidu coverage.
    "baidu-maps": {
        "description": "百度地图（国内）：地理编码、POI、路线、天气、路况（https://lbsyun.baidu.com）",
        "required_env": ("BAIDU_MAP_API_KEY",),
        "node": ("@baidumap/mcp-server-baidu-map@1.0.5", "mcp-server-baidu-map"),
    },
    "amap-maps": {
        "description": "高德地图（国内）：地理编码 maps_geo、天气 maps_weather、路线、POI（https://lbs.amap.com）",
        "required_env": ("AMAP_MAPS_API_KEY",),
        "node": ("@amap/amap-maps-mcp-server@0.0.8", "mcp-amap"),
    },
    # Flights: repository-owned Duffel v2 MCP.
    "duffel-flights": {
        "description": "Duffel v2 航班搜索（全球官方 API，https://duffel.com）",
        "required_env": ("DUFFEL_API_KEY_LIVE",),
        "python_script": "mcp_servers/flights/duffel_mcp.py",
    },
    # Rail: repository-owned 12306 MCP.
    "12306-train": {
        "description": "12306 火车票与车次查询服务（仓库内实现，零 Key，国内）",
        "python_script": "mcp_servers/rail/rail_12306_mcp.py",
    },
    # Weather: Open-Meteo, no key required.
    "open-meteo": {
        "description": "Open-Meteo MCP：当前天气、固定 7 日预报、历史天气与空气质量（零 Key，https://open-meteo.com）",
        "node": ("open-meteo-mcp@0.1.0", "weather-mcp"),
    },
    # Currency: repository-owned Frankfurter wrapper, no key required.
    "currency-exchange-mcp": {
        "description": "实时汇率换算（内置 Frankfurter API，无需 API Key，不依赖 Node）",
        "python_script": "mcp_servers/currency/frankfurter_mcp.py",
    },
}


def _node_fields(package: str, binary: str) -> Dict[str, object]:
    """Use a checked-in Node binary when available, otherwise use versioned npx."""

    local_bin = _REPO_ROOT / "node_modules" / ".bin" / binary
    if local_bin.exists():
        return {"command": str(local_bin), "args": []}
    return {"command": "npx", "args": ["-y", package]}


def _python_fields(*, script: Optional[str] = None, module: Optional[str] = None) -> Dict[str, object]:
    if script is not None:
        path = _REPO_ROOT.joinpath(*script.split("/"))
        return {"command": sys.executable, "args": [str(path)]}
    if module is not None:
        return {"command": sys.executable, "args": ["-m", module]}
    raise ValueError("MCP Python server must define script or module")


def _server_env(required_env: tuple[str, ...]) -> Optional[Dict[str, str]]:
    """Read provider-native environment variables on every call."""

    if not required_env:
        return None
    return {name: value for name in required_env if (value := os.getenv(name))}


def default_mcp_servers() -> Dict[str, MCPServerItem]:
    """Build the default MCP server map from the direct in-code declarations."""

    servers: Dict[str, MCPServerItem] = {}
    for name, declaration in _DEFAULT_SERVERS.items():
        node = declaration.get("node")
        if node is not None:
            launch = _node_fields(*node)
        else:
            launch = _python_fields(
                script=declaration.get("python_script"),
                module=declaration.get("python_module"),
            )
        required_env = tuple(declaration.get("required_env", ()))
        servers[name] = MCPServerItem(
            **launch,
            env=_server_env(required_env),
            description=declaration["description"],
            required_env=list(required_env),
        )
    return servers
