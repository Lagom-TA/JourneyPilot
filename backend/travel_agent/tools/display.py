from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict
from urllib.parse import urlsplit

from .governance import (
    TOOL_FAILURE_SUMMARY,
    is_tool_execution_envelope,
    looks_like_machine_payload,
    summarize_tool_result,
)

logger = logging.getLogger(__name__)


def _summarize_args(arguments: Dict[str, Any]) -> str:
    """将工具参数压缩为单行可读字符串。"""
    if not arguments:
        return ""
    parts = []
    for k, v in arguments.items():
        v_str = str(v)
        if len(v_str) > 60:
            v_str = v_str[:57] + "..."
        parts.append(f"{k}={v_str}")
    return ", ".join(parts)


TOOL_CATEGORIES: Dict[str, str] = {
    "global_place_search": "search",
    "maps_geo": "internal",
    "maps_text_search": "search",
    "maps_around_search": "search",
    "maps_weather": "data",
    "maps_direction_driving": "data",
    "maps_direction_walking": "data",
    "maps_direction_transit_integrated": "data",
    "get-station-code-of-citys": "internal",
    "get-tickets": "data",
    "get-interline-tickets": "data",
    "search_flights": "data",
    "free_web_search": "search",
}


def _extract_geocode_summary(result: Dict[str, Any]) -> str:
    try:
        content_str = result.get("content", "")
        if isinstance(content_str, list):
            content_str = content_str[0].get("text", "") if content_str else ""
        if isinstance(content_str, str) and content_str.startswith("{"):
            data = json.loads(content_str)

            results = data.get("results")
            if isinstance(results, list) and results:
                loc_str = results[0].get("location")
                if isinstance(loc_str, str) and "," in loc_str:
                    lng_s, lat_s = loc_str.split(",", 1)
                    addr = (
                        results[0].get("formatted_address")
                        or results[0].get("level")
                        or ""
                    )
                    prefix = f"已定位 {addr}" if addr else "已定位坐标"
                    return f"{prefix}（{float(lat_s):.4f}°N, {float(lng_s):.4f}°E）"
            loc = data.get("location", {})
            lat = loc.get("lat", "")
            lng = loc.get("lng", "")
            address = data.get("formatted_address") or data.get("level") or ""
            if lat and lng:
                if address:
                    return f"已定位 {address}（{float(lat):.4f}°N, {float(lng):.4f}°E）"
                return f"已定位坐标（{float(lat):.4f}°N, {float(lng):.4f}°E）"
    except Exception:
        pass
    return "地理编码完成"


def _extract_weather_summary(result: Dict[str, Any]) -> str:
    try:
        content_str = result.get("content", "")
        if isinstance(content_str, list):
            content_str = content_str[0].get("text", "") if content_str else ""
        if isinstance(content_str, str) and content_str.startswith("{"):
            data = json.loads(content_str)
            forecasts = data.get("forecasts", [{}])
            if forecasts:
                f = forecasts[0]
                city = f.get("city", "")
                casts = f.get("casts", [{}])
                if casts:
                    today = casts[0]
                    weather = today.get("dayweather", "")
                    high = today.get("nighttemp", "")
                    low = today.get("daytemp", "")
                    parts = [city, weather]
                    if high and low:
                        parts.append(f"{low}~{high}°C")
                    return " ".join(p for p in parts if p)
    except Exception:
        pass
    return "天气查询完成"


def _extract_search_summary(result: Dict[str, Any]) -> str:
    try:
        content_str = result.get("content", "")
        if isinstance(content_str, list):
            content_str = content_str[0].get("text", "") if content_str else ""
        if isinstance(content_str, str) and content_str.startswith("{"):
            data = json.loads(content_str)
            results = data.get("results", [])
            if results:
                names = [r.get("name", "") for r in results[:3] if r.get("name")]
                suffix = f"等 {len(results)} 个地点"
                if names:
                    return f"找到 {suffix}：{', '.join(names)}"
                return f"找到 {suffix}"
    except Exception:
        pass
    return "搜索完成"


def _extract_web_search_summary(result: Dict[str, Any]) -> str:
    try:
        content_str = result.get("content", "")
        if isinstance(content_str, list):
            items = [c.get("text", "") for c in content_str if isinstance(c, dict)]
            content_str = " ".join(items)
        if isinstance(content_str, str):
            lines = [line.strip() for line in content_str.split("\n") if line.strip()]
            if lines:
                preview = "" if looks_like_machine_payload(lines[0]) else lines[0][:60]
                return f"搜索到 {len(lines)} 条结果" + (
                    f"：{preview}…" if preview else ""
                )
    except Exception:
        pass
    return "网络搜索完成"


def _extract_direction_summary(result: Dict[str, Any]) -> str:
    try:
        content_str = result.get("content", "")
        if isinstance(content_str, list):
            content_str = content_str[0].get("text", "") if content_str else ""
        if isinstance(content_str, str) and content_str.startswith("{"):
            data = json.loads(content_str)
            routes = data.get("routes", [{}])
            if routes:
                r = routes[0]
                distance = r.get("distance", "")
                duration = r.get("duration", "")
                parts = []
                if distance:
                    dist_km = (
                        int(distance) / 1000 if str(distance).isdigit() else distance
                    )
                    parts.append(
                        f"{dist_km:.1f}km"
                        if isinstance(dist_km, float)
                        else str(dist_km)
                    )
                if duration:
                    mins = int(duration) // 60 if str(duration).isdigit() else duration
                    parts.append(
                        f"约 {mins} 分钟" if isinstance(mins, int) else str(mins)
                    )
                if parts:
                    return "路线：" + "，".join(parts)
    except Exception:
        pass
    return "路线规划完成"


def _extract_station_summary(result: Dict[str, Any]) -> str:
    try:
        content_str = result.get("content", "")
        if isinstance(content_str, list):
            content_str = content_str[0].get("text", "") if content_str else ""
        if isinstance(content_str, str) and content_str.startswith("{"):
            data = json.loads(content_str)
            stations = [
                v.get("station_name", k) for k, v in data.items() if isinstance(v, dict)
            ]
            if stations:
                return f"已获取车站代码：{', '.join(stations)}"
    except Exception:
        pass
    return "车站代码查询完成"


_TOOL_SEMANTIC_SUMMARIZERS: Dict[str, Any] = {
    "global_place_search": _extract_search_summary,
    "maps_geo": _extract_geocode_summary,
    "maps_geocode": _extract_geocode_summary,
    "maps_weather": _extract_weather_summary,
    "maps_text_search": _extract_search_summary,
    "maps_around_search": _extract_search_summary,
    "maps_search_places": _extract_search_summary,
    "maps_direction_driving": _extract_direction_summary,
    "maps_direction_walking": _extract_direction_summary,
    "maps_direction_transit_integrated": _extract_direction_summary,
    "maps_directions": _extract_direction_summary,
    "free_web_search": _extract_web_search_summary,
    "get-station-code-of-citys": _extract_station_summary,
}


def _summarize_tool_result(tool_name: str, result: Dict[str, Any]) -> str:
    """按工具类型生成语义化摘要，用于 UI 展示。"""
    if not result:
        return "无结果"
    if is_tool_execution_envelope(result):
        return str(result.get("result_summary") or "无结果")
    if result.get("type") == "user_input_required":
        return "等待用户输入"
    if not result.get("success", True):
        return TOOL_FAILURE_SUMMARY

    summarizer = _TOOL_SEMANTIC_SUMMARIZERS.get(tool_name)
    if summarizer:
        try:
            summary = summarizer(result)
            if summary:
                return summary
        except Exception as e:
            logger.debug(f"工具摘要器 [{tool_name}] 异常: {e}")

    return summarize_tool_result(result)


def public_text(value: Any, limit: int = 300) -> str:
    """Fail closed for structured/partial payloads, including prose-prefixed JSON."""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if re.search(
        r'\{\s*(?:["}\[]|$)|```|<think|"[\w_]+"\s*:|contract_version|research_packet_id',
        text,
    ):
        return ""
    if text.startswith(("[", "{")):
        return ""
    return text[:limit]


def result_preview(value: Any, depth: int = 0) -> list[dict[str, str]]:
    """Bounded allowlist of place/page/route facts; never serialize arbitrary data."""
    if depth > 10:
        return []
    if isinstance(value, str):
        try:
            return result_preview(json.loads(value), depth + 1)
        except (ValueError, TypeError):
            return []
    if isinstance(value, list):
        rows: list[dict[str, str]] = []
        for item in value[:12]:
            for row in result_preview(item, depth + 1):
                if row not in rows:
                    rows.append(row)
        return rows[:6]
    if not isinstance(value, dict):
        return []
    if "sanitized_result" in value:
        return result_preview(value["sanitized_result"], depth + 1)
    title = public_text(value.get("name") or value.get("title"), 120)
    if not title:
        origin, destination = value.get("from_endpoint"), value.get("to_endpoint")
        if isinstance(origin, dict) and isinstance(destination, dict):
            a, b = (
                public_text(origin.get("name"), 60),
                public_text(destination.get("name"), 60),
            )
            if a and b:
                title = f"{a} → {b}"
    if title:
        row = {"title": title}
        detail = public_text(
            value.get("detail")
            or value.get("address")
            or value.get("description")
            or value.get("snippet"),
            240,
        )
        minutes = value.get("duration_minutes")
        if not detail and isinstance(minutes, (int, float)) and minutes > 0:
            detail = f"约 {minutes:g} 分钟"
        if detail and detail != title:
            row["detail"] = detail
        url = value.get("url")
        if isinstance(url, str):
            try:
                parsed = urlsplit(url)
                if (
                    parsed.scheme in {"http", "https"}
                    and parsed.hostname
                    and not parsed.username
                    and not parsed.password
                ):
                    row["url"] = url[:1000]
            except ValueError:
                pass
        return [row]
    rows = []
    for key in (
        "results",
        "places",
        "pois",
        "web",
        "routes",
        "data",
        "content",
        "text",
    ):
        if key in value:
            rows.extend(result_preview(value[key], depth + 1))
    return rows[:6]
