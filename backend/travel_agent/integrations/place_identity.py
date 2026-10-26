"""不同类型 Provider 地点身份的统一格式。"""

from __future__ import annotations

from typing import Optional
import re


_OSM_TYPE = re.compile(r"^(node|way|relation)$")


def stable_place_id_12306(station_telecode: str) -> Optional[str]:
    """返回 ``12306:{telecode}``；telecode 为空时返回 None。

    telecode 通常是三个拉丁字母（如 BJP），但 provider 也可能返回其他非空车站
    代码；只有空值会被拒绝。
    """
    code = str(station_telecode or "").strip().upper()
    if not code:
        return None
    return f"12306:{code}"


def stable_place_id_amap_poi(poi_id: str) -> Optional[str]:
    """返回 ``amap:poi:{poi_id}``；poi_id 为空时返回 None。"""
    poi = str(poi_id or "").strip()
    if not poi:
        return None
    if poi.startswith("amap:poi:"):
        return poi
    return f"amap:poi:{poi}"


def stable_place_id_osm(osm_type: str, osm_id: str | int) -> Optional[str]:
    """返回 ``osm:{type}:{id}``；type 或 id 不合法时返回 None。"""
    kind = str(osm_type or "").strip().lower()
    raw_id = str(osm_id or "").strip()
    if not _OSM_TYPE.fullmatch(kind):
        return None
    if not raw_id.isdigit() or raw_id == "0":
        return None
    return f"osm:{kind}:{raw_id}"
