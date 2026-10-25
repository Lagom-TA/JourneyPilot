"""Planning research transport rail parsing."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional

from travel_agent.integrations.rail.stations import city_station_telecodes

_RAIL_RECORD_TEXT_FIELDS = (
    "train_code",
    "from_name",
    "from_code",
    "to_name",
    "to_code",
    "departure_time",
    "arrival_time",
)


def _extract_tool_text(envelope: Mapping[str, Any]) -> str:
    """Collect any text payload from an MCP tool envelope, defensively."""
    parts: List[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            text = node.get("text")
            if node.get("type") == "text" and isinstance(text, str):
                parts.append(text)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(envelope.get("sanitized_result"))
    if not parts:
        summary = envelope.get("result_summary")
        if isinstance(summary, str):
            parts.append(summary)
    return "\n".join(parts)


def _normalize_cn_city_for_rail(name: str) -> str:
    """把带行政级别后缀的中文城市名收敛成 12306 认得的裸城市名。"""
    text = (name or "").strip()
    for suffix in ("特别行政区", "市", "省", "地区", "盟"):
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return text


_CN_CITY_STATION_TELECODES: Dict[str, tuple[str, ...]] = {
    "上海": ("AOH", "SHH"),
    "深圳": ("IOQ", "SZQ"),
    "北京": ("VNP", "BJP"),
    "广州": ("IZQ", "GZQ"),
    "杭州": ("HGH", "HZH"),
    "南京": ("NJH", "NKH"),
    "成都": ("ICW", "CDW"),
    "武汉": ("WHN",),
    "西安": ("XAY",),
    "重庆": ("CUW", "CQW"),
    "天津": ("TIP", "TJP"),
    "苏州": ("SZH",),
    "厦门": ("XMS",),
    "长沙": ("CSQ",),
    "郑州": ("ZAF", "ZZF"),
    "青岛": ("QDK",),
    "大连": ("DFT", "DLT"),
    "昆明": ("KMM",),
    "福州": ("FYS", "FZS"),
    "济南": ("JNK",),
    "合肥": ("HFH",),
    "南昌": ("NCG",),
    "石家庄": ("SJP",),
    "哈尔滨": ("HBB",),
    "沈阳": ("SYT",),
    "宁波": ("NGH",),
    "无锡": ("WXH",),
    "东莞": ("RTQ",),
    "佛山": ("FSQ",),
    "珠海": ("ZIQ",),
}


def _builtin_station_telecode(city_name: str) -> Optional[str]:
    """Return the preferred (first) builtin station telecode for a CN city."""
    bare = _normalize_cn_city_for_rail(city_name)
    codes = _CN_CITY_STATION_TELECODES.get(bare) or _CN_CITY_STATION_TELECODES.get(
        city_name.strip()
    )
    return codes[0] if codes else None


def _builtin_station_telecode_candidates(city_name: str) -> List[str]:
    """Return ordered station telecodes to try for get-tickets (HSR hubs first)."""
    bare = _normalize_cn_city_for_rail(city_name)
    codes = _CN_CITY_STATION_TELECODES.get(bare) or _CN_CITY_STATION_TELECODES.get(
        city_name.strip()
    )
    return list(codes) if codes else []


def _parse_station_codes(text: str) -> Dict[str, str]:
    """Parse {city_name: station_code} from get-station-code-of-citys output."""
    codes: Dict[str, str] = {}
    for match in re.finditer(
        r'"([^"]+)"\s*:\s*\{[^{}]*?"station_code"\s*:\s*"([A-Za-z0-9]+)"', text
    ):
        codes[match.group(1)] = match.group(2)

    for match in re.finditer(
        r"([^\s,;:：\"']{2,12})\s*[：:]\s*([A-Za-z]{3})",
        text,
    ):
        city, code = match.group(1).strip(), match.group(2).upper()
        if city and code not in codes.values():
            codes.setdefault(city, code)
    return codes


def _rail_train_records(envelope: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Read the structured ``get-tickets`` rows out of a Tool Gateway envelope."""
    result = envelope.get("sanitized_result")
    if not isinstance(result, Mapping):
        return []
    rows = result.get("results")
    if not isinstance(rows, list):
        return []
    trains: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping) or row.get("truncated") is True:
            continue
        train = {
            field: str(row.get(field) or "").strip()
            for field in _RAIL_RECORD_TEXT_FIELDS
        }
        duration = row.get("duration_minutes")
        price = row.get("min_price_cny")
        if not all(train.values()) or not isinstance(duration, int):
            continue
        train["duration_minutes"] = duration
        train["min_price_cny"] = (
            float(price)
            if isinstance(price, (int, float)) and not isinstance(price, bool)
            else None
        )
        trains.append(train)
    return trains


def _rail_station_scope(city_name: str, requested_code: str) -> frozenset[str]:
    """Every station telecode that legitimately represents one trip endpoint."""
    return frozenset(
        city_station_telecodes(_normalize_cn_city_for_rail(city_name))
        | {requested_code}
    )


def _filter_rail_trains_by_station_scope(
    trains: List[Dict[str, Any]],
    *,
    from_scope: frozenset[str],
    to_scope: frozenset[str],
) -> List[Dict[str, Any]]:
    """Drop city-group rows whose endpoints are not the trip's endpoints."""

    return [
        train
        for train in trains
        if str(train.get("from_code") or "") in from_scope
        and str(train.get("to_code") or "") in to_scope
    ]
