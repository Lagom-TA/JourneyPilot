"""Integrations place identity."""

from __future__ import annotations

from typing import Optional
import re


_OSM_TYPE = re.compile(r"^(node|way|relation)$")


def stable_place_id_12306(station_telecode: str) -> Optional[str]:
    """Return ``12306:{telecode}`` or None when the telecode is empty.

    Telecodes are usually three Latin letters (e.g. BJP), but providers may
    emit other non-empty station codes; only emptiness fails closed.
    """
    code = str(station_telecode or "").strip().upper()
    if not code:
        return None
    return f"12306:{code}"


def stable_place_id_amap_poi(poi_id: str) -> Optional[str]:
    """Return ``amap:poi:{poi_id}`` or None when poi_id is empty."""
    poi = str(poi_id or "").strip()
    if not poi:
        return None
    if poi.startswith("amap:poi:"):
        return poi
    return f"amap:poi:{poi}"


def stable_place_id_osm(osm_type: str, osm_id: str | int) -> Optional[str]:
    """Return ``osm:{type}:{id}`` or None when type/id are invalid."""
    kind = str(osm_type or "").strip().lower()
    raw_id = str(osm_id or "").strip()
    if not _OSM_TYPE.fullmatch(kind):
        return None
    if not raw_id.isdigit() or raw_id == "0":
        return None
    return f"osm:{kind}:{raw_id}"
