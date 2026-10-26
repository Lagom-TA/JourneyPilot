"""12306 余票行的解析、票价解码与输出组装。"""

from __future__ import annotations

from dataclasses import dataclass
from travel_agent.integrations.rail.stations import station_group_telecodes
from typing import Any
from typing import Mapping
from typing import Optional
from typing import Sequence
import re


_DIGITS_RE = re.compile(r"^\d+$")


NO_TRAIN_MESSAGE = "没有查询到相关车次信息"


_IDX_TRAIN_NO = 2


_IDX_STATION_TRAIN_CODE = 3


_IDX_FROM_TELECODE = 6


_IDX_TO_TELECODE = 7


_IDX_START_TIME = 8


_IDX_ARRIVE_TIME = 9


_IDX_LISHI = 10


_IDX_CAN_WEB_BUY = 11


_IDX_START_TRAIN_DATE = 13


_IDX_YP_INFO_NEW = 39


_ROW_FIELD_COUNT = 40


_SEAT_TYPES: Mapping[str, tuple[str, str]] = {
    "9": ("商务座", "swz"),
    "P": ("特等座", "tz"),
    "M": ("一等座", "zy"),
    "D": ("优选一等座", "zy"),
    "O": ("二等座", "ze"),
    "S": ("二等包座", "ze"),
    "6": ("高级软卧", "gr"),
    "A": ("高级动卧", "gr"),
    "4": ("软卧", "rw"),
    "I": ("一等卧", "rw"),
    "F": ("动卧", "rw"),
    "3": ("硬卧", "yw"),
    "J": ("二等卧", "yw"),
    "2": ("软座", "rz"),
    "1": ("硬座", "yz"),
    "W": ("无座", "wz"),
    "H": ("其他", "qt"),
}


_SEAT_COUNT_INDEX: Mapping[str, int] = {
    "gr": 21,
    "qt": 22,
    "rw": 23,
    "rz": 24,
    "tz": 25,
    "wz": 26,
    "yw": 28,
    "yz": 29,
    "ze": 30,
    "zy": 31,
    "swz": 32,
}


_PRICE_CHUNK_LENGTH = 10


_NO_SEAT_COUNT_MARKER = 3000


@dataclass(frozen=True)
class SeatPrice:
    seat_name: str
    short: str
    price: float
    inventory: str


@dataclass(frozen=True)
class RailTicket:
    train_no: str
    train_code: str
    from_name: str
    from_telecode: str
    to_name: str
    to_telecode: str
    start_time: str
    arrive_time: str
    lishi: str
    start_train_date: str
    can_web_buy: str
    prices: tuple[SeatPrice, ...]


def _safe_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0


def decode_seat_prices(
    yp_info: str, seat_inventory: Mapping[str, str]
) -> list[SeatPrice]:
    """把 ``yp_info_new`` 解码为每类座位的票价与余票，保持上游顺序。"""

    prices: list[SeatPrice] = []
    blob = yp_info or ""
    for offset in range(0, len(blob) - _PRICE_CHUNK_LENGTH + 1, _PRICE_CHUNK_LENGTH):
        chunk = blob[offset : offset + _PRICE_CHUNK_LENGTH]
        if _safe_int(chunk[6:10]) >= _NO_SEAT_COUNT_MARKER:
            seat_code = "W"
        elif chunk[0] not in _SEAT_TYPES:
            seat_code = "H"
        else:
            seat_code = chunk[0]
        seat_name, short = _SEAT_TYPES[seat_code]
        prices.append(
            SeatPrice(
                seat_name=seat_name,
                short=short,
                price=_safe_int(chunk[1:6]) / 10,
                inventory=str(seat_inventory.get(short, "")),
            )
        )
    return prices


def parse_left_ticket_rows(
    rows: Sequence[str], station_names: Mapping[str, str]
) -> list[RailTicket]:
    """把 ``data.result`` 行转成车票，站名取自 ``data.map``。"""

    tickets: list[RailTicket] = []
    for row in rows:
        fields = str(row).split("|")
        if len(fields) < _ROW_FIELD_COUNT:
            continue
        from_telecode = fields[_IDX_FROM_TELECODE]
        to_telecode = fields[_IDX_TO_TELECODE]
        inventory = {short: fields[index] for short, index in _SEAT_COUNT_INDEX.items()}
        tickets.append(
            RailTicket(
                train_no=fields[_IDX_TRAIN_NO],
                train_code=fields[_IDX_STATION_TRAIN_CODE],
                from_name=station_names.get(from_telecode, from_telecode),
                from_telecode=from_telecode,
                to_name=station_names.get(to_telecode, to_telecode),
                to_telecode=to_telecode,
                start_time=fields[_IDX_START_TIME],
                arrive_time=fields[_IDX_ARRIVE_TIME],
                lishi=fields[_IDX_LISHI],
                start_train_date=fields[_IDX_START_TRAIN_DATE],
                can_web_buy=fields[_IDX_CAN_WEB_BUY],
                prices=tuple(decode_seat_prices(fields[_IDX_YP_INFO_NEW], inventory)),
            )
        )
    return tickets


def format_ticket_status(inventory: str) -> str:
    """把 12306 的一个余票字段渲染为可读的余票说明。"""

    value = (inventory or "").strip()
    if _DIGITS_RE.match(value):
        count = int(value)
        return "无票" if count == 0 else f"剩余{count}张票"
    if value in {"有", "充足"}:
        return "有票"
    if value in {"无", "--", ""}:
        return "无票"
    if value == "候补":
        return "无票需候补"
    return f"{value}票"


def _format_price(price: float) -> str:
    return str(int(price)) if float(price).is_integer() else str(price)


def _format_ticket_block(ticket: RailTicket) -> str:
    lines = [
        f"{ticket.train_code} "
        f"{ticket.from_name}(telecode:{ticket.from_telecode}) -> "
        f"{ticket.to_name}(telecode:{ticket.to_telecode}) "
        f"{ticket.start_time} -> {ticket.arrive_time} 历时：{ticket.lishi}"
    ]
    for seat in ticket.prices:
        lines.append(
            f"- {seat.seat_name}: {format_ticket_status(seat.inventory)} "
            f"{_format_price(seat.price)}元"
        )
    return "\n".join(lines)


def format_tickets_text(tickets: Sequence[RailTicket]) -> str:
    """把各段渲染为文本，仅用于 ``get-interline-tickets`` 的嵌套输出。

    ``get-tickets`` 使用 :func:`build_left_ticket_payload`：经过治理清洗后，文本
    对代码消费方不可用。中转文本只由模型阅读，因此保持文本形式。
    """

    if not tickets:
        return NO_TRAIN_MESSAGE
    blocks = "\n".join(_format_ticket_block(ticket) for ticket in tickets)
    return "车次|出发站 -> 到达站|出发时间 -> 到达时间|历时\n" + blocks + "\n"


MAX_TICKET_RECORDS = 120


_MAX_FARE_SUMMARY_CHARS = 120


_SECOND_CLASS_SEAT_NAME = "二等座"


_CLOCK_RE = re.compile(r"^\d{1,2}:\d{2}$")


_LISHI_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def seat_is_bookable(inventory: str) -> bool:
    """一个 12306 余票字段是否表示该座席当前可购买。

    ``候补``（waitlist）不可购买：旅行者无法持有该座位，用它绑定车段会声明一个
    实际买不到的行程。
    """

    value = (inventory or "").strip()
    if _DIGITS_RE.match(value):
        return int(value) > 0
    return value in {"有", "充足"}


def lishi_to_minutes(lishi: str) -> Optional[int]:
    """``00:45`` → ``45``；12306 返回无法解析的历时则返回 ``None``。"""

    match = _LISHI_RE.match((lishi or "").strip())
    if match is None:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def _fare_summary(ticket: RailTicket) -> str:
    """覆盖全部座席的一行简短标量文本，用于报告界面。"""

    text = " / ".join(
        f"{seat.seat_name} {format_ticket_status(seat.inventory)} "
        f"{_format_price(seat.price)}元"
        for seat in ticket.prices
    )
    if len(text) > _MAX_FARE_SUMMARY_CHARS:
        return text[: _MAX_FARE_SUMMARY_CHARS - 1].rstrip() + "…"
    return text


def build_ticket_record(ticket: RailTicket) -> Optional[dict[str, Any]]:
    """把一趟可购车次压成 11 个标量键的扁平记录。

    没有可购座席，或 12306 返回的时间表无法转成车段（时刻或历时不可解析）时返回
    ``None``：无法放到时间轴上的行不能作为路线证据。
    """

    bookable = [
        seat.price for seat in ticket.prices if seat_is_bookable(seat.inventory)
    ]
    duration_minutes = lishi_to_minutes(ticket.lishi)
    if (
        not bookable
        or duration_minutes is None
        or not _CLOCK_RE.match(ticket.start_time)
        or not _CLOCK_RE.match(ticket.arrive_time)
    ):
        return None

    second_class = next(
        (
            seat.price
            for seat in ticket.prices
            if seat.seat_name == _SECOND_CLASS_SEAT_NAME
        ),
        None,
    )
    return {
        "train_code": ticket.train_code,
        "from_name": ticket.from_name,
        "from_code": ticket.from_telecode,
        "to_name": ticket.to_name,
        "to_code": ticket.to_telecode,
        "departure_time": ticket.start_time,
        "arrival_time": ticket.arrive_time,
        "duration_minutes": duration_minutes,
        "min_price_cny": min(bookable),
        "second_class_price_cny": second_class,
        "fare_summary": _fare_summary(ticket),
    }


def build_left_ticket_payload(
    tickets: Sequence[RailTicket],
    *,
    date: str,
    from_code: str,
    to_code: str,
) -> dict[str, Any]:
    """``get-tickets`` 的载荷：关于可购车次的事实，不包含选择策略。

    这里只做三项 Provider 事实缩减：

    1. 丢弃不属于查询车站城市组的行：12306 把查询扩展到整个城市组（见
       :func:`station_group_telecodes`），上海南 → 杭州南 的行回答的是另一段行程；
    2. 丢弃没有可购座席的行（:func:`seat_is_bookable`）；
    3. 把票价表压成扁平标量（:func:`build_ticket_record`）。

    清洗器最多保留 ``MAX_TICKET_RECORDS`` 行，而一次真实查询可能返回数百行，
    因此截断顺序很重要：先保留查询车站对完全匹配的行，再保留城市组内的其他车站，
    各组内部保持 12306 的行顺序。这个顺序不会为了城市组行丢弃完全匹配行，也不会
    在完全匹配没有车次时丢掉城市组内的真实车段（例如上海 → 兰州实际到达兰州西）。
    保留哪些车次由 agent 层决定。
    """

    from_scope = station_group_telecodes(from_code)
    to_scope = station_group_telecodes(to_code)
    records = [
        record
        for record in (
            build_ticket_record(ticket)
            for ticket in tickets
            if ticket.from_telecode in from_scope and ticket.to_telecode in to_scope
        )
        if record is not None
    ]
    ordered = sorted(
        records,
        key=lambda record: (
            0
            if record["from_code"] == from_code and record["to_code"] == to_code
            else 1
        ),
    )
    return {
        "success": True,
        "provider": "12306",
        "tool_name": "get-tickets",
        "date": date,
        "from_station": from_code,
        "to_station": to_code,
        "bookable_train_count": len(ordered),
        "returned_train_count": min(len(ordered), MAX_TICKET_RECORDS),
        "results": ordered[:MAX_TICKET_RECORDS],
    }
