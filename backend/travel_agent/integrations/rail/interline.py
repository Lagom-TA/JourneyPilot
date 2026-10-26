"""12306 中转行程的解析与格式化。"""

from __future__ import annotations

from travel_agent.integrations.rail.errors import Rail12306Error
from travel_agent.integrations.rail.tickets import NO_TRAIN_MESSAGE
from travel_agent.integrations.rail.tickets import RailTicket
from travel_agent.integrations.rail.tickets import _SEAT_COUNT_INDEX
from travel_agent.integrations.rail.tickets import decode_seat_prices
from travel_agent.integrations.rail.tickets import format_tickets_text
from typing import Any
from typing import Mapping
from typing import Sequence
import re


_ALL_LISHI_RE = re.compile(r"(?:(\d+)小时)?(\d+)分钟")


def normalize_all_lishi(all_lishi: str) -> str:
    """``9小时37分钟`` → ``09:37``，与 get-tickets 的历时格式一致。"""

    match = _ALL_LISHI_RE.search(all_lishi or "")
    if match is None:
        raise Rail12306Error(f"12306 中转历时无法解析: {all_lishi!r}")
    hours = match.group(1) or "0"
    return f"{int(hours):02d}:{int(match.group(2)):02d}"


def _interline_legs(itinerary: Mapping[str, Any]) -> list[RailTicket]:
    legs: list[RailTicket] = []
    for leg in itinerary.get("fullList") or ():
        inventory = {
            short: str(leg.get(f"{short}_num", "")) for short in _SEAT_COUNT_INDEX
        }
        legs.append(
            RailTicket(
                train_no=str(leg.get("train_no", "")),
                train_code=str(leg.get("station_train_code", "")),
                from_name=str(leg.get("from_station_name", "")),
                from_telecode=str(leg.get("from_station_telecode", "")),
                to_name=str(leg.get("to_station_name", "")),
                to_telecode=str(leg.get("to_station_telecode", "")),
                start_time=str(leg.get("start_time", "")),
                arrive_time=str(leg.get("arrive_time", "")),
                lishi=str(leg.get("lishi", "")),
                start_train_date=str(leg.get("start_train_date", "")),
                can_web_buy="",
                prices=tuple(
                    decode_seat_prices(str(leg.get("yp_info", "")), inventory)
                ),
            )
        )
    return legs


def format_interline_text(itineraries: Sequence[Mapping[str, Any]]) -> str:
    """按行程嵌套的文本：一行表头，随后是制表符缩进的各段。"""

    if not itineraries:
        return NO_TRAIN_MESSAGE
    parts = [
        "出发时间 -> 到达时间 | 出发车站 -> 中转车站 -> 到达车站 | 换乘标志 "
        "|换乘等待时间| 总历时\n"
    ]
    for itinerary in itineraries:
        transfer = (
            "同车换乘"
            if str(itinerary.get("same_train")) == "Y"
            else "同站换乘"
            if str(itinerary.get("same_station")) == "0"
            else "换站换乘"
        )
        parts.append(
            f"{itinerary.get('train_date')} {itinerary.get('start_time')} -> "
            f"{itinerary.get('arrive_date')} {itinerary.get('arrive_time')} | "
            f"{itinerary.get('from_station_name')} -> "
            f"{itinerary.get('middle_station_name')} -> "
            f"{itinerary.get('end_station_name')} | "
            f"{transfer} | {itinerary.get('wait_time')} | "
            f"{normalize_all_lishi(str(itinerary.get('all_lishi', '')))}\n"
        )
        nested = format_tickets_text(_interline_legs(itinerary))
        parts.append("\t" + nested.replace("\n", "\n\t"))
        parts.append("\n")
    return "".join(parts)
