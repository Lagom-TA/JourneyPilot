"""12306 三项查询的载荷组装。"""

from __future__ import annotations

from travel_agent.integrations.rail.client import Rail12306Client
from travel_agent.integrations.rail.interline import format_interline_text
from travel_agent.integrations.rail.stations import CITY_NOT_FOUND_MESSAGE
from travel_agent.integrations.rail.stations import _require_station_code
from travel_agent.integrations.rail.stations import city_station_code
from travel_agent.integrations.rail.stations import station_table
from travel_agent.integrations.rail.tickets import build_left_ticket_payload
from travel_agent.integrations.rail.tickets import parse_left_ticket_rows
from typing import Any
from typing import Optional
import httpx
import json


async def get_tickets_payload(
    date: str,
    from_station: str,
    to_station: str,
    *,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> dict[str, Any]:
    """``get-tickets``：一对车站的真实可购车次，结构化输出。"""

    from_code = _require_station_code(from_station, role="fromStation")
    to_code = _require_station_code(to_station, role="toStation")
    client = Rail12306Client(transport=transport)
    rows, names = await client.fetch_left_tickets(
        date=date, from_code=from_code, to_code=to_code
    )
    return build_left_ticket_payload(
        parse_left_ticket_rows(rows, names),
        date=date,
        from_code=from_code,
        to_code=to_code,
    )


async def get_interline_tickets_text(
    date: str,
    from_station: str,
    to_station: str,
    middle_station: str = "",
    *,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> str:
    """``get-interline-tickets``：一对车站的真实一次换乘行程。"""

    from_code = _require_station_code(from_station, role="fromStation")
    to_code = _require_station_code(to_station, role="toStation")
    middle_code = (
        _require_station_code(middle_station, role="middleStation")
        if (middle_station or "").strip()
        else ""
    )
    client = Rail12306Client(transport=transport)
    itineraries = await client.fetch_interline(
        date=date,
        from_code=from_code,
        to_code=to_code,
        middle_code=middle_code,
    )
    return format_interline_text(itineraries)


def get_station_code_of_citys_text(citys: str) -> str:
    """``get-station-code-of-citys``：每个中文城市对应的车站。

    ``citys`` 是单个以 ``|`` 分隔的字符串（例如 ``"上海|杭州"``）；参数名与
    形状是仓库内所有调用方依赖的接口。
    """

    result: dict[str, dict[str, str]] = {}
    for city in (citys or "").split("|"):
        name = city.strip()
        if not name:
            continue
        telecode = city_station_code(name)
        if telecode is None:
            result[name] = {"error": CITY_NOT_FOUND_MESSAGE}
            continue
        result[name] = {
            "station_code": telecode,
            "station_name": station_table()[telecode].name,
        }
    return json.dumps(result, ensure_ascii=False)
