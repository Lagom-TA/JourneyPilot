"""Integrations rail stations."""

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
    """Parse the official ``station_name.js`` body into ``{telecode: station}``."""

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
    """``{telecode: RailStation}`` from the committed offline snapshot."""

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
    """Every station telecode 12306 files under ``city`` (empty if unknown)."""

    return frozenset(
        station.telecode for station in _stations_by_city().get(city.strip(), ())
    )


def station_group_telecodes(telecode: str) -> frozenset[str]:
    """Every telecode 12306 answers with when one station is queried.

    A remaining-ticket query is expanded by 12306 to the whole city station
    group: asking ``from_station=AOH`` (上海虹桥) also returns rows departing
    上海南, 上海松江 and 金山北.  The grouping is the provider's own — city is
    field ``[7]`` of the official station table — so reading it back is fact
    work, not a repo judgement.  The queried station is always in the group even
    when the snapshot does not know it.
    """

    station = station_table().get((telecode or "").strip())
    if station is None:
        return frozenset({telecode})
    return frozenset(city_station_telecodes(station.city) | {telecode})


def city_station_code(city: str) -> Optional[str]:
    """The station representing a city: the one whose name equals the city name."""

    for station in _stations_by_city().get(city.strip(), ()):
        if station.name == station.city:
            return station.telecode
    return None


def resolve_station_code(value: str) -> Optional[str]:
    """Accept a telecode or a 中文 station name (with or without a trailing 站)."""

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
