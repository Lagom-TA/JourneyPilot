"""站表快照的来源与一致性诊断。"""

from __future__ import annotations

from travel_agent.integrations.rail.stations import STATION_SNAPSHOT_META_PATH
from travel_agent.integrations.rail.stations import STATION_SNAPSHOT_PATH
from travel_agent.integrations.rail.stations import station_table
from typing import Any
from typing import Optional
import json


def station_snapshot_metadata() -> Optional[dict[str, Any]]:
    """读取快照的来源侧车文件；无法读取时返回 ``None``。

    刻意不抛异常：治理探针需要能够报告「不可读」，而不是让调用方失败。
    ``station_snapshot_freshness`` 会把 ``None`` 转成明确的 ``unknown`` 判定，
    不会转成「最新」。
    """

    try:
        return json.loads(STATION_SNAPSHOT_META_PATH.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def station_snapshot_fingerprint_drift() -> list[str]:
    """已提交快照与其声明指纹不一致的地方。

    12306 只提供字节数与记录数两种指纹，因此它们用于发现截断或只替换了一半的
    刷新；这类问题否则会表现为某个城市悄悄缺少车站。
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
