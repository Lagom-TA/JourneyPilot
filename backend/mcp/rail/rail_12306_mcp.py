#!/usr/bin/env python3
"""JourneyPilot-owned 12306 MCP server.

The server keeps the three tool names and argument shapes the repo couples to,
and reads the live query path out of ``/otn/leftTicket/init`` on every call.
All decode logic lives in ``travel_agent.integrations.rail`` so it is unit
testable without a subprocess.  ``get-tickets`` answers with a JSON payload
(structured, code-consumed); ``get-interline-tickets`` and
``get-station-code-of-citys`` answer with the text/JSON string their only
consumers read.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from travel_agent.integrations.rail.queries import get_interline_tickets_text, get_station_code_of_citys_text, get_tickets_payload


server = Server("journeypilot-12306-rail")

_STATION_ARG_DESCRIPTION = (
    "出发地/到达地的中文车站名（如 \"上海虹桥\"）或 12306 `station_code` 电报码"
    "（如 \"AOH\"，可通过 `get-station-code-of-citys` 查询）"
)
_DATE_ARG_DESCRIPTION = (
    "查询日期，格式为 \"yyyy-MM-dd\"。12306 常规余票窗口为今天起 15 天内。"
)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get-tickets",
            description=(
                "查询 12306 真实余票信息：返回 JSON，results 为可购票车次列表，每条含 "
                "train_code、出发/到达车站名与电报码、departure_time/arrival_time、"
                "duration_minutes、min_price_cny（最低可购席别票价）、"
                "second_class_price_cny 与 fare_summary（各席别票价与余票状态）。"
            ),
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "date": {
                        "type": "string",
                        "format": "date",
                        "description": _DATE_ARG_DESCRIPTION,
                    },
                    "fromStation": {
                        "type": "string",
                        "description": _STATION_ARG_DESCRIPTION,
                    },
                    "toStation": {
                        "type": "string",
                        "description": _STATION_ARG_DESCRIPTION,
                    },
                },
                "required": ["date", "fromStation", "toStation"],
            },
        ),
        Tool(
            name="get-interline-tickets",
            description=(
                "查询 12306 真实中转换乘余票信息：返回每条换乘方案的总历时、"
                "换乘车站与等待时间，以及各段车次的时刻与票价。"
            ),
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "date": {
                        "type": "string",
                        "format": "date",
                        "description": _DATE_ARG_DESCRIPTION,
                    },
                    "fromStation": {
                        "type": "string",
                        "description": _STATION_ARG_DESCRIPTION,
                    },
                    "toStation": {
                        "type": "string",
                        "description": _STATION_ARG_DESCRIPTION,
                    },
                    "middleStation": {
                        "type": "string",
                        "description": "可选：指定中转车站的中文名或 `station_code`。",
                    },
                },
                "required": ["date", "fromStation", "toStation"],
            },
        ),
        Tool(
            name="get-station-code-of-citys",
            description="通过中文城市名查询代表该城市的 12306 `station_code`。",
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "citys": {
                        "type": "string",
                        "description": (
                            "要查询的城市，比如 \"上海\"。查询多个城市时用 | 分隔，"
                            "比如 \"上海|杭州\"。"
                        ),
                    }
                },
                "required": ["citys"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "get-tickets":
        # 行程绑定需要读取结构化车次信息。工具管理器会先解开 JSON，
        # 避免后续结果治理将整段文本压缩并截断。
        text = json.dumps(
            await get_tickets_payload(
                str(arguments["date"]),
                str(arguments["fromStation"]),
                str(arguments["toStation"]),
            ),
            ensure_ascii=False,
        )
    elif name == "get-interline-tickets":
        text = await get_interline_tickets_text(
            str(arguments["date"]),
            str(arguments["fromStation"]),
            str(arguments["toStation"]),
            str(arguments.get("middleStation") or ""),
        )
    elif name == "get-station-code-of-citys":
        text = get_station_code_of_citys_text(str(arguments["citys"]))
    else:
        raise ValueError(f"unknown tool: {name}")
    return [TextContent(type="text", text=text)]


async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
