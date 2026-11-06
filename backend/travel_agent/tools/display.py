from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict
from urllib.parse import urlsplit

from .governance import (
    TOOL_FAILURE_SUMMARY,
    is_tool_execution_envelope,
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


_SENSITIVE_ARG_KEY = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|cookie|passport|"
    r"id[_-]?card|phone|mobile|email|证件|身份证|护照|手机号|邮箱)",
    re.IGNORECASE,
)


def _trim_quotes(value: str) -> str:
    return value.strip().strip("'\"").strip()


def public_args_summary(value: Any, limit: int = 200) -> str:
    """把工具参数压成可公开的一行；敏感键脱敏，结构化载荷丢弃。

    原始参数仍由 ``_summarize_args`` 写入审计 trace。这里只服务 SSE、思维链和
    历史恢复，不能把 ``api_key`` / ``passport`` 等键值带进客户端载荷。
    """
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, dict):
        parts: list[str] = []
        for key in sorted(parsed):
            if _SENSITIVE_ARG_KEY.search(str(key)):
                parts.append(f"{key}=[已隐藏]")
                continue
            item = parsed[key]
            if isinstance(item, (dict, list)):
                continue
            item_text = public_text(str(item), 60)
            if item_text:
                parts.append(f"{key}={item_text}")
        return ", ".join(parts)[:limit]
    parts = []
    for part in re.split(r",\s+(?=[\w.-]+\s*=)", text):
        key, separator, raw = part.partition("=")
        if not separator:
            continue
        key = key.strip()
        if _SENSITIVE_ARG_KEY.search(key):
            parts.append(f"{key}=[已隐藏]")
            continue
        item_text = public_text(_trim_quotes(raw), 60)
        if item_text:
            parts.append(f"{key}={item_text}")
    if parts:
        return ", ".join(parts)[:limit]
    return public_text(text, limit)


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
    return "地点定位完成"


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
                    # 高德 casts 里 daytemp 是白天最高温，nighttemp 是夜间最低温。
                    low = today.get("nighttemp", "")
                    high = today.get("daytemp", "")
                    parts = [city, weather]
                    if high and low:
                        parts.append(f"{low}~{high}°C")
                    return " ".join(p for p in parts if p)
    except Exception:
        pass
    return "天气查询完成"


def _place_identity_key(item: Any) -> tuple[str, ...] | None:
    if not isinstance(item, dict):
        return None
    place_id = str(item.get("place_id") or "").strip()
    if place_id:
        return ("id", place_id)
    name = str(
        item.get("name")
        or item.get("title")
        or item.get("branch_name")
        or item.get("property_name")
        or ""
    ).strip()
    address = str(item.get("address") or item.get("formatted_address") or "").strip()
    if not name and not address:
        return None
    return ("name", name.casefold(), address.casefold())


def _unique_place_items(results: list[Any]) -> list[Any]:
    unique: list[Any] = []
    seen: set[tuple[str, ...]] = set()
    for item in results:
        key = _place_identity_key(item)
        if key is None or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _extract_search_summary(result: Dict[str, Any]) -> str:
    try:
        content_str = result.get("content", "")
        if isinstance(content_str, list):
            content_str = content_str[0].get("text", "") if content_str else ""
        if isinstance(content_str, str) and content_str.startswith("{"):
            data = json.loads(content_str)
            results = data.get("results", [])
            if results:
                unique = _unique_place_items(results)
                count = len(unique) if unique else len(results)
                names = [
                    str(
                        item.get("name")
                        or item.get("title")
                        or item.get("branch_name")
                        or item.get("property_name")
                        or ""
                    ).strip()
                    for item in unique[:3]
                ]
                names = [name for name in names if name]
                if names:
                    return f"找到 {count} 个地点：{'、'.join(names)}"
                return f"找到 {count} 个地点"
    except Exception:
        pass
    return "搜索完成"


def _extract_web_search_summary(result: Dict[str, Any]) -> str:
    # 结构化 {web: [...]} 交给统一摘要；纯文本 content 只取第一行可公开预览，
    # 不把行数冒充结果数，也不把整段 JSON 当预览。
    content = result.get("content")
    if isinstance(content, list):
        content = " ".join(
            str(item.get("text") or "") for item in content if isinstance(item, dict)
        )
    if isinstance(content, str):
        lines = [line.strip() for line in content.split("\n") if line.strip()]
        preview = public_text(lines[0], 80) if lines else ""
        if preview:
            return f"网页资料：{preview}"
    return summarize_tool_result(result)


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
                        f"{dist_km:.1f} 公里"
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
                return f"已获取车站代码：{'、'.join(stations)}"
    except Exception:
        pass
    return "车站代码查询完成"


_TOOL_SEMANTIC_SUMMARIZERS: Dict[str, Any] = {
    "global_place_search": _extract_search_summary,
    "maps_geo": _extract_geocode_summary,
    "maps_weather": _extract_weather_summary,
    "maps_text_search": _extract_search_summary,
    "maps_around_search": _extract_search_summary,
    "maps_direction_driving": _extract_direction_summary,
    "maps_direction_walking": _extract_direction_summary,
    "maps_direction_transit_integrated": _extract_direction_summary,
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
    """结构化或不完整载荷返回空串；带正文前缀的 JSON 也算载荷。"""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if re.search(
        r'\{\s*(?:["}\[]|$)|```|<think|"[\w_]+"\s*:|research_packet_id',
        text,
    ):
        return ""
    if text.startswith(("[", "{")):
        return ""
    return text[:limit]


_PLACE_TYPE_TOKEN_LABELS: tuple[tuple[str, str], ...] = (
    ("museum", "博物馆"),
    ("gallery", "艺术馆"),
    ("artwork", "艺术馆"),
    ("viewpoint", "观景点"),
    ("attraction", "景点"),
    ("tourism", "景点"),
    ("park", "公园"),
    ("garden", "花园"),
    ("restaurant", "餐厅"),
    ("cafe", "咖啡馆"),
    ("coffee", "咖啡馆"),
    ("bar", "酒吧"),
    ("food_court", "美食广场"),
    ("fast_food", "快餐"),
    ("hotel", "住宿"),
    ("hostel", "住宿"),
    ("guest_house", "住宿"),
    ("motel", "住宿"),
    ("resort", "住宿"),
    ("apartment", "住宿"),
    ("lodging", "住宿"),
    ("station", "车站"),
    ("railway", "车站"),
    ("airport", "机场"),
    ("aerodrome", "机场"),
    ("university", "校园"),
    ("college", "校园"),
    ("school", "学校"),
    ("library", "图书馆"),
    ("mall", "商场"),
    ("shopping", "商场"),
    ("market", "市场"),
    ("temple", "寺庙"),
    ("shrine", "寺庙"),
    ("monastery", "寺庙"),
    ("church", "教堂"),
    ("cathedral", "教堂"),
    ("beach", "海滩"),
    ("mountain", "山"),
    ("peak", "山"),
    ("lake", "湖"),
    ("hospital", "医院"),
    ("theatre", "剧场"),
    ("theater", "剧场"),
    ("zoo", "动物园"),
    ("aquarium", "水族馆"),
    ("stadium", "体育场"),
    ("administrative", "行政区"),
    ("boundary", "行政区"),
)
_PLACE_TYPE_MARKER_LABELS: tuple[tuple[str, str], ...] = (
    ("博物馆", "博物馆"),
    ("美术馆", "艺术馆"),
    ("风景名胜", "景点"),
    ("景点", "景点"),
    ("公园", "公园"),
    ("花园", "花园"),
    ("餐厅", "餐厅"),
    ("餐饮", "餐厅"),
    ("咖啡", "咖啡馆"),
    ("酒吧", "酒吧"),
    ("酒店", "住宿"),
    ("旅馆", "住宿"),
    ("宾馆", "住宿"),
    ("客栈", "住宿"),
    ("民宿", "住宿"),
    ("度假村", "住宿"),
    ("火车站", "车站"),
    ("车站", "车站"),
    ("机场", "机场"),
    ("大学", "校园"),
    ("学校", "学校"),
    ("图书馆", "图书馆"),
    ("商场", "商场"),
    ("购物", "商场"),
    ("市场", "市场"),
    ("寺庙", "寺庙"),
    ("教堂", "教堂"),
    ("海滩", "海滩"),
    ("山峰", "山"),
    ("山岳", "山"),
    ("湖泊", "湖"),
    ("医院", "医院"),
    ("剧场", "剧场"),
    ("动物园", "动物园"),
    ("水族馆", "水族馆"),
    ("体育场", "体育场"),
    ("行政区", "行政区"),
)
_COLLECTION_LABELS: Dict[str, str] = {
    "destinations": "目的地资料",
    "local_culture": "本地文化",
    "visa_policies": "签证政策",
    "travel_tips": "旅行提示",
    "travel_knowledge": "我的资料库",
}


def _safe_public_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = urlsplit(text)
    except ValueError:
        return None
    if (
        parsed.scheme in {"http", "https"}
        and parsed.hostname
        and not parsed.username
        and not parsed.password
    ):
        return text[:1000]
    return None


def _public_place_type(value: Any) -> str:
    text = public_text(value, 120)
    if not text:
        return ""
    lowered = text.casefold()
    tokens = {token for token in re.split(r"[^a-z0-9]+", lowered) if token}
    for token, label in _PLACE_TYPE_TOKEN_LABELS:
        if token in tokens:
            return label
    for marker, label in _PLACE_TYPE_MARKER_LABELS:
        if marker in text:
            return label
    return ""


def _public_distance(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    if value <= 0:
        # 0 只说明坐标重合，负数不是有效距离；都不能据此补充
        # “就在目的地附近”这类旅行事实。
        return ""
    if value < 1:
        return f"距目的地约 {max(1, round(value * 1000))} 米"
    return f"距目的地约 {value:.1f} 公里"


def _public_address(value: Any, title: str) -> str:
    text = public_text(value, 200)
    if not text:
        return ""
    parts = [part.strip() for part in re.split(r"[,，]", text) if part.strip()]
    if parts and title and parts[0].casefold() == title.casefold():
        parts = parts[1:]
    return "，".join(parts)[:80]


_SECRET_TEXT_RE = re.compile(
    r"(?:api[_-]?key|secret|token|password|passwd|authorization|cookie|"
    r"passport|id[_-]?card)\s*[:=]\s*\S+",
    re.IGNORECASE,
)


def _public_excerpt(value: Any, limit: int = 240) -> str:
    text = public_text(value, limit)
    if not text or _SECRET_TEXT_RE.search(text):
        return ""
    return text


def _public_source_name(value: Any) -> str:
    """URL 只留 hostname，本地路径只留 basename；绝不输出绝对路径。"""
    text = public_text(value, 200)
    if not text:
        return ""
    parsed = urlsplit(text)
    if parsed.scheme in {"http", "https"} and parsed.hostname:
        return parsed.hostname[:120]
    normalized = text.replace("\\", "/").rstrip("/")
    if "/" in normalized:
        base = normalized.rsplit("/", 1)[-1]
        stem = base.rsplit(".", 1)[0] if "." in base else base
        if "__" in stem:
            stem = stem.split("__", 1)[1]
        return (stem or base)[:120]
    return text[:120]


def _document_preview_rows(documents: list[Any], depth: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for doc in documents[:6]:
        if not isinstance(doc, dict):
            continue
        content = _public_excerpt(doc.get("content"), 240)
        source = _public_source_name(doc.get("source"))
        collection = _COLLECTION_LABELS.get(str(doc.get("collection") or "").strip(), "")
        if not content and not source and not collection:
            continue
        title = source or collection or "资料库"
        detail_parts: list[str] = []
        if collection and collection != title:
            detail_parts.append(collection)
        published = public_text(doc.get("published_at"), 40)
        if published:
            detail_parts.append(published)
        if content:
            detail_parts.append(content)
        row: dict[str, str] = {"title": title}
        detail = " · ".join(detail_parts)
        if detail and detail != title:
            row["detail"] = detail[:240]
        url = _safe_public_url(doc.get("url")) or _safe_public_url(doc.get("source"))
        if url:
            row["url"] = url
        if row not in rows:
            rows.append(row)
    return rows[:6]


def result_preview(value: Any, depth: int = 0) -> list[dict[str, str]]:
    """按白名单提取地点/网页/知识库/路线的有限字段，不序列化任意数据。"""
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
    documents = value.get("documents")
    if isinstance(documents, list) and (
        documents or value.get("failures") or value.get("retrieval_status") is not None
    ):
        return _document_preview_rows(documents, depth)
    title = public_text(
        value.get("name")
        or value.get("title")
        or value.get("branch_name")
        or value.get("property_name")
        or value.get("hotel_name")
        or value.get("poi_name"),
        120,
    )
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
        detail_parts: list[str] = []
        place_type = _public_place_type(value.get("provider_place_type"))
        if place_type:
            detail_parts.append(place_type)
        distance = _public_distance(value.get("destination_distance_km"))
        if distance:
            detail_parts.append(distance)
        address = _public_address(
            value.get("address") or value.get("formatted_address") or value.get("location"),
            title,
        )
        if address:
            detail_parts.append(address)
        if not detail_parts:
            detail = public_text(
                value.get("detail")
                or value.get("description")
                or value.get("snippet"),
                240,
            )
            if detail and detail != title:
                detail_parts.append(detail)
        if not detail_parts:
            minutes = value.get("duration_minutes")
            if isinstance(minutes, (int, float)) and not isinstance(minutes, bool) and minutes > 0:
                detail_parts.append(f"约 {minutes:g} 分钟")
        if not detail_parts:
            meters = value.get("distance_meters")
            if isinstance(meters, (int, float)) and not isinstance(meters, bool) and meters > 0:
                detail_parts.append(f"约 {meters / 1000:.1f} 公里")
        detail = " · ".join(detail_parts)
        if detail and detail != title:
            row["detail"] = detail[:240]
        url = _safe_public_url(value.get("url"))
        if url:
            row["url"] = url
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
