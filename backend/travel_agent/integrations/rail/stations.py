"""12306 站表快照的解析与查询。"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from travel_agent.integrations.rail.errors import Rail12306Error
from travel_agent.integrations.rail.errors import StationNotFoundError
from travel_agent.paths import BACKEND_DIR
from typing import Mapping
from typing import Optional
import re


_TELECODE_RE = re.compile(r"^[A-Z]+$")


CITY_NOT_FOUND_MESSAGE = "未检索到城市。"


STATION_SNAPSHOT_PATH = BACKEND_DIR / "mcp" / "rail" / "station_name.js"


STATION_SNAPSHOT_META_PATH = STATION_SNAPSHOT_PATH.with_name("station_name.meta.json")


@dataclass(frozen=True)
class RailStation:
    telecode: str
    name: str
    pinyin: str
    pinyin_abbr: str
    short_abbr: str
    city: str


def parse_station_snapshot(raw: str) -> dict[str, RailStation]:
    """把官方 ``station_name.js`` 内容解析成 ``{telecode: station}``。"""

    body_match = re.search(r"='(.*)'", raw, re.S)
    if body_match is None:
        raise Rail12306Error("12306 station snapshot is not a station_names assignment")
    stations: dict[str, RailStation] = {}
    for record in body_match.group(1).split("@"):
        if not record:
            continue
        fields = record.split("|")
        if len(fields) < 8:
            continue
        telecode = fields[2].strip()
        name = fields[1].strip()
        if not telecode or not name:
            continue
        stations[telecode] = RailStation(
            telecode=telecode,
            name=name,
            pinyin=fields[3].strip(),
            pinyin_abbr=fields[0].strip(),
            short_abbr=fields[4].strip(),
            city=fields[7].strip(),
        )
    if not stations:
        raise Rail12306Error("12306 station snapshot decoded to zero stations")
    return stations


@lru_cache(maxsize=1)
def station_table() -> Mapping[str, RailStation]:
    """从已提交的离线快照返回 ``{telecode: RailStation}``。"""

    return parse_station_snapshot(STATION_SNAPSHOT_PATH.read_text("utf-8"))


@lru_cache(maxsize=1)
def _stations_by_name() -> Mapping[str, RailStation]:
    return {station.name: station for station in station_table().values()}


@lru_cache(maxsize=1)
def _stations_by_city() -> Mapping[str, tuple[RailStation, ...]]:
    grouped: dict[str, list[RailStation]] = {}
    for station in station_table().values():
        grouped.setdefault(station.city, []).append(station)
    return {
        city: tuple(sorted(members, key=lambda item: item.telecode))
        for city, members in grouped.items()
    }


def city_station_telecodes(city: str) -> frozenset[str]:
    """12306 归在 ``city`` 下的全部车站电报码（城市未知时为空）。"""

    return frozenset(
        station.telecode for station in _stations_by_city().get(city.strip(), ())
    )


def station_group_telecodes(telecode: str) -> frozenset[str]:
    """查询一个车站时 12306 实际会返回的全部电报码。

    余票查询会被 12306 扩展到整个城市车站组：查询 ``from_station=AOH``（上海虹桥）
    也会返回从上海南、上海松江与金山北出发的车次。分组由 Provider 自己给出
    （城市是官方站表的第 ``[7]`` 个字段），这里只是读取该事实。即使快照不认识
    被查询的车站，它本身也总在返回集合中。
    """

    station = station_table().get((telecode or "").strip())
    if station is None:
        return frozenset({telecode})
    return frozenset(city_station_telecodes(station.city) | {telecode})


def city_station_code(city: str) -> Optional[str]:
    """代表一个城市的车站：名称与城市名相同的那一个。"""

    for station in _stations_by_city().get(city.strip(), ()):
        if station.name == station.city:
            return station.telecode
    return None


def resolve_station_code(value: str) -> Optional[str]:
    """接受电报码或中文站名（可带末尾的「站」）。"""

    text = (value or "").strip()
    if not text:
        return None
    if _TELECODE_RE.match(text) and text in station_table():
        return text
    if text.endswith("站") and len(text) > 1:
        text = text[:-1]
    station = _stations_by_name().get(text)
    return station.telecode if station else None


def _require_station_code(value: str, *, role: str) -> str:
    code = resolve_station_code(value)
    if code is None:
        raise StationNotFoundError(f"{role} 不是有效的车站名或 station_code: {value!r}")
    return code
