"""Integrations rail snapshot diagnostics."""

from __future__ import annotations

from travel_agent.integrations.rail.stations import STATION_SNAPSHOT_META_PATH
from travel_agent.integrations.rail.stations import STATION_SNAPSHOT_PATH
from travel_agent.integrations.rail.stations import city_station_telecodes
from travel_agent.integrations.rail.stations import station_table
from typing import Any
from typing import Mapping
from typing import Optional
from typing import Sequence
import json


def station_snapshot_metadata() -> Optional[dict[str, Any]]:
    """Read the snapshot's sidecar provenance, or ``None`` if it cannot be read.

    Deliberately total: a governance probe must be able to report "unreadable"
    rather than take down whatever asked.  ``station_snapshot_freshness`` turns
    ``None`` into an explicit ``unknown`` verdict — never into "current".
    """

    try:
        return json.loads(STATION_SNAPSHOT_META_PATH.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def station_snapshot_fingerprint_drift() -> list[str]:
    """Ways the committed snapshot disagrees with the fingerprint it declares.

    Byte size and record count are the only fingerprint 12306 hands out, so they
    are the only thing that can catch a truncated or half-replaced refresh — the
    failure mode that otherwise shows up as a city quietly missing its stations.
    """

    metadata = station_snapshot_metadata()
    if metadata is None:
        return ["站表 meta 缺失或不可解析"]
    problems: list[str] = []
    declared_bytes = metadata.get("byte_size")
    if isinstance(declared_bytes, int):
        actual_bytes = STATION_SNAPSHOT_PATH.stat().st_size
        if actual_bytes != declared_bytes:
            problems.append(
                f"字节数不符：实际 {actual_bytes}，meta 声明 {declared_bytes}"
            )
    declared_records = metadata.get("record_count")
    if isinstance(declared_records, int):
        actual_records = len(station_table())
        if actual_records != declared_records:
            problems.append(
                f"记录数不符：实际 {actual_records}，meta 声明 {declared_records}"
            )
    return problems


def city_station_membership_drift(
    table: Mapping[str, Sequence[str]],
) -> list[str]:
    """Name every hand-maintained telecode the official snapshot disagrees with.

    Membership — does this telecode exist, and does 12306 file it under this city —
    is decidable offline from the committed snapshot in milliseconds, so the
    hand-written hub table never has to be trusted on that point ("no
    shape-level alternative criterion" holds only for the *ordering*,
    which upstream does not publish).

    Returns the drift instead of raising, and there is no "skip on drift" branch
    anywhere: a caller either reports it or fails, and the fix is to correct the
    table.
    """

    stations = station_table()
    problems: list[str] = []
    for city, telecodes in table.items():
        members = city_station_telecodes(city)
        for telecode in telecodes:
            station = stations.get(telecode)
            if station is None:
                problems.append(f"{city}/{telecode}：官方快照里没有这个电报码")
            elif telecode not in members:
                problems.append(
                    f"{city}/{telecode}：官方快照把它归在 {station.city}（{station.name}）"
                )
    return problems
