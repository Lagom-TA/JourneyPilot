from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..config.models import AgentToolPolicy
from .registry import get_tool_registry

logger = logging.getLogger(__name__)


class ToolAccessUnavailable(RuntimeError):
    """工具目录读不到。调用方必须显式失败，不能当成“没有工具”继续跑。"""


def exclude_tools(
    available: List[Dict[str, Any]],
    excluded: List[str],
) -> List[Dict[str, Any]]:
    """移除在之前的修复轮次中持久失败的工具。"""
    if not excluded:
        return available
    excluded_set = set(excluded)
    return [
        tool
        for tool in available
        if tool.get("schema", {}).get("function", {}).get("name", "")
        not in excluded_set
    ]


async def get_available_tools() -> List[Dict[str, Any]]:
    "从工具注册表获取可用工具列表。"
    try:
        registry = get_tool_registry()
        from ..config.loader import get_settings

        tools = registry.get_tools_as_schemas()
        if not get_settings().embedding.enabled:
            tools = [
                tool
                for tool in tools
                if tool["schema"]["function"]["name"] != "knowledge_search"
            ]
        return tools
    except Exception as exc:
        logger.exception("获取工具列表失败")
        raise ToolAccessUnavailable("工具目录暂时不可用") from exc


def filter_tools_for_agent(
    tools: List[Dict[str, Any]],
    agent_name: str,
) -> List[Dict[str, Any]]:
    "按 Agent 工具策略（_AGENT_TOOL_POLICY）过滤工具。"
    from ..config.loader import get_settings

    if not get_settings().embedding.enabled:
        tools = [
            item
            for item in tools
            if item.get("schema", {}).get("function", {}).get("name")
            != "knowledge_search"
        ]
    policy = (
        AgentToolPolicy(
            servers=set(),
            deny_tools={"ask_user"},
            extra_tools={
                "knowledge_search",
                "free_web_search",
                "tavily_search",
                "brave_web_search",
                "latest_exchange_rates",
            },
        )
        if agent_name == "fast_answer_agent"
        else _AGENT_TOOL_POLICY.get(agent_name)
    )

    if policy is None:
        return [
            t
            for t in tools
            if t.get("source") != "mcp"
            and t.get("schema", {}).get("function", {}).get("name", "")
            not in _SCOPED_NON_MCP_TOOLS
        ]

    deny_tools = policy.deny_tools

    if "*" in deny_tools:
        return []

    allowed_servers = policy.servers
    extra_tools = policy.extra_tools

    result = []
    for t in tools:
        tool_name = t.get("schema", {}).get("function", {}).get("name", "")
        server_name = t.get("server_name")

        if t.get("source") == "mcp":
            owner = _EXTRA_MCP_TOOL_OWNERS.get(tool_name)
            if tool_name in _SCOPED_NON_MCP_TOOLS or (owner and server_name != owner):
                continue

        if agent_name == "fast_answer_agent" and tool_name not in extra_tools:
            continue

        if tool_name in deny_tools:
            continue

        if t.get("source") != "mcp":
            if tool_name in _SCOPED_NON_MCP_TOOLS and tool_name not in extra_tools:
                continue
            result.append(t)
        elif t.get("server_name") in allowed_servers:
            result.append(t)
        elif tool_name in extra_tools:
            result.append(t)

    logger.debug(
        "filter_tools_for_agent(%s): %d -> %d tools [%s]",
        agent_name,
        len(tools),
        len(result),
        ", ".join(
            t.get("schema", {}).get("function", {}).get("name", "?") for t in result
        ),
    )
    return result


_AGENT_TOOL_POLICY: Dict[str, AgentToolPolicy] = {
    # 需求理解：联网资料与真实地点检索，先查后问；提问由理解门承担，不用 ask_user。
    "understanding_agent": AgentToolPolicy(
        deny_tools={"ask_user"},
        servers={"tavily-search", "brave-search", "duckduckgo-search"},
        extra_tools={
            "free_web_search",
            "knowledge_search",
            "global_place_search",
            "maps_text_search",
            "maps_search_detail",
        },
    ),
    "destination_researcher": AgentToolPolicy(
        deny_tools={"ask_user"},
        servers={
            "tavily-search",
            "brave-search",
            "firecrawl",
            "duckduckgo-search",
            "fetch",
        },
        extra_tools={
            "free_web_search",
            "knowledge_search",
            "global_place_search",
            "maps_text_search",
            "maps_around_search",
            "maps_search_detail",
        },
    ),
    "transport_researcher": AgentToolPolicy(
        servers={
            "12306-train", "duffel-flights", "amap-maps",
            "tavily-search", "brave-search", "duckduckgo-search", "fetch",
        },
        deny_tools={"maps_geo", "maps_weather", "ask_user"},
        extra_tools={
            "free_web_search", "global_place_search", "global_route_search", "knowledge_search"
        },
    ),
    "accommodation_researcher": AgentToolPolicy(
        servers={"tavily-search", "brave-search", "currency-exchange-mcp"},
        deny_tools={"ask_user"},
        extra_tools={
            "free_web_search",
            "knowledge_search",
            "global_place_search",
            "global_route_search",
            "maps_text_search",
            "maps_around_search",
            "maps_search_detail",
        },
    ),
    "itinerary_planner": AgentToolPolicy(
        # 组合只查询安排所需地点，交通问题交给交通研究员。
        servers=set(),
        deny_tools={"ask_user", "knowledge_search", "global_route_search", "free_web_search"},
        extra_tools={
            "global_place_search",
            "maps_text_search",
            "maps_around_search",
            "maps_search_detail",
        },
    ),
}


_SCOPED_NON_MCP_TOOLS = {
    "global_place_search",
    "global_route_search",
    "knowledge_search",
}

_EXTRA_MCP_TOOL_OWNERS = {
    "free_web_search": "duckduckgo-search",
    "tavily_search": "tavily-search",
    "brave_web_search": "brave-search",
    "latest_exchange_rates": "currency-exchange-mcp",
    "maps_text_search": "amap-maps",
    "maps_around_search": "amap-maps",
    "maps_search_detail": "amap-maps",
}
