"""交付内容的来源展示。"""

from __future__ import annotations

from travel_agent.planning.research.evidence import SourceRecord
from typing import Any
from typing import Mapping
import json
import re


_PAYLOAD_RESULT_KEYS = ("results", "content")

PUBLIC_FACT_FIELD_LABELS: dict[str, str] = {
    "name": "名称",
    "branch_name": "餐厅名称",
    "property_name": "住宿名称",
    "place_id": "地点信息",
    "provider_place_type": "地点类型",
    "provider_country_code": "所在国家或地区",
    "address": "地址",
    "latitude": "坐标",
    "longitude": "坐标",
    "opening_window": "开放时间",
    "reservation_required": "预约要求",
    "visit_type": "类型",
    "meal_type": "餐次",
    "cuisine_types": "菜系",
    "average_spend_cny": "人均消费",
    "estimated_cost_cny": "参考费用",
    "nightly_price_cny": "每晚价格",
    "total_price_cny": "整段价格",
    "check_in_date": "入住日期",
    "check_out_date": "退房日期",
    "check_in_time": "入住时间",
    "check_out_time": "退房时间",
    "nights": "入住晚数",
    "room_type": "房型",
    "facilities": "设施",
    "availability_status": "房态",
    "from_endpoint": "出发站点",
    "to_endpoint": "到达站点",
    "boarding_stop": "上车站点",
    "alighting_stop": "下车站点",
    "selected_mode": "交通方式",
    "segments": "班次与路线",
    "departure_at": "出发时间",
    "arrival_at": "抵达时间",
    "duration_minutes": "耗时",
    "distance_meters": "距离",
    "transfer_count": "换乘",
    "booking_status": "预订要求",
    "total_cost_cny": "票价",
    "condition_label": "天气状况",
    "high_c": "最高气温",
    "low_c": "最低气温",
    "precipitation_probability_pct": "降水概率",
    "wind_speed_kph": "风速",
}

_TOOL_SOURCE_TITLE_LABELS: dict[str, str] = {
    "get-tickets": "车次查询结果",
    "get-interline-tickets": "中转车次查询结果",
    "get-station-code-of-citys": "车站代码查询结果",
    "search_flights": "航班查询结果",
    "global_place_search": "地点搜索结果",
    "maps_text_search": "地点搜索结果",
    "maps_around_search": "周边搜索结果",
    "maps_geo": "地点定位结果",
    "maps_weather": "天气查询结果",
    "maps_direction_driving": "驾车路线查询结果",
    "maps_direction_walking": "步行路线查询结果",
    "maps_direction_transit_integrated": "公共交通路线查询结果",
    "free_web_search": "网页搜索结果",
    "tavily_search": "网页搜索结果",
    "brave_web_search": "网页搜索结果",
    "firecrawl_search": "网页搜索结果",
    "knowledge_search": "资料库检索结果",
}

_MACHINE_KV_PREFIX_RE = re.compile(
    r"^(?:\s*[a-z][a-z0-9]*(?:_[a-z0-9]+)+=[^，,；;\s]+[，,；;\s]*)+"
)
_INLINE_MACHINE_KV_RE = re.compile(
    r"[，,；;\s]*\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+=[^，,；;\s]+[，,；;]?"
)
_ROUTE_MIN_UNIT_RE = re.compile(r"\b(\d+)\s*min\b")
_WEATHER_FORECAST_SUFFIX_RE = re.compile(r"\s+weather forecast$", re.IGNORECASE)
_TOOL_QUERY_TITLE_RE = re.compile(r"^([A-Za-z0-9_:-]+)\s+查询结果$")
_TOOL_DEGRADATION_TITLE_RE = re.compile(r"^[A-Za-z0-9_:-]+\s+degradation$", re.IGNORECASE)


def public_fact_field_label(label: str) -> str:
    """将事实字段路径映射为面向用户的中文标签。"""
    cleaned = str(label or "").strip()
    return PUBLIC_FACT_FIELD_LABELS.get(cleaned, cleaned)


def clean_public_source_excerpt(excerpt: str) -> str:
    """清理来源摘录中的机器键值对、内部术语与英文单位，保留旅行事实。"""
    text = str(excerpt or "").strip()
    if not text:
        return ""
    cleaned = _MACHINE_KV_PREFIX_RE.sub("", text).strip()
    cleaned = _INLINE_MACHINE_KV_RE.sub("", cleaned).strip(" ，,；;")
    cleaned = cleaned.replace("POI 编码与经纬度", "地点位置与坐标")
    cleaned = _WEATHER_FORECAST_SUFFIX_RE.sub(" 天气预报", cleaned)
    cleaned = _ROUTE_MIN_UNIT_RE.sub(r"\1 分钟", cleaned)
    return cleaned or text


def clean_public_source_title(
    title: str, excerpt: str = "", *, source_record_id: str = ""
) -> str:
    """清理来源标题中的英文工具名与内部记录前缀。"""
    raw = str(title or "").strip()
    lowered = raw.lower()
    if " place record: " in lowered:
        entity_name = raw.split(":", 1)[-1].strip()
        return f"地点资料：{entity_name}"
    if " route: " in lowered:
        route_label = str(excerpt or "").split(" · ", 1)[0].strip()
        return f"交通路线：{route_label}" if route_label else "交通路线"
    if source_record_id.startswith("weather-source-"):
        return "天气参考"
    m = _TOOL_QUERY_TITLE_RE.match(raw)
    if m:
        tool_key = m.group(1).lower()
        return _TOOL_SOURCE_TITLE_LABELS.get(tool_key, "工具查询结果")
    if _TOOL_DEGRADATION_TITLE_RE.match(raw):
        return "备用来源记录"
    return raw


def _payload_public_excerpt(payload: object) -> tuple[str | None, str | None]:
    """把结构化搜索载荷转成一段可读摘要与 URL。"""

    if not isinstance(payload, dict):
        return None, None
    usable: list[dict] = []
    for key in _PAYLOAD_RESULT_KEYS:
        entries = payload.get(key)
        if isinstance(entries, list):
            usable = [item for item in entries if isinstance(item, dict)]
            if usable:
                break
    if not usable:
        return None, None
    first = usable[0]
    title = str(first.get("title") or "").strip()
    snippet = str(first.get("snippet") or "").strip()
    excerpt = "。".join(part for part in (title, snippet) if part)
    if len(excerpt) > 360:
        excerpt = f"{excerpt[:357].rstrip()}…"
    url = str(first.get("url") or "").strip() or None
    return excerpt or f"已核对 {len(usable)} 条外部结果。", url


def _json_public_excerpt(value: str) -> tuple[str | None, str | None]:
    if not value.lstrip().startswith(("{", "[")):
        return None, None
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None, None
    return _payload_public_excerpt(payload)


_READABLE_FIELDS = (
    "title",
    "name",
    "display_name",
    "label",
    "snippet",
    "description",
    "summary",
    "address",
    "formatted_address",
)


def _readable_bits(entry: Mapping[str, Any]) -> list[str]:
    """从一条记录里挑出能读的几段，保持 ``_READABLE_FIELDS`` 的顺序。"""

    bits: list[str] = []
    for field in _READABLE_FIELDS:
        value = entry.get(field)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            text = str(value).strip()
            if text and text not in bits:
                bits.append(text)
    return bits


def _rendered_payload_excerpt(payload: object) -> str | None:
    """把任意结构化载荷渲染为可读文本；卡片上不出现原始 JSON。

    ``_payload_public_excerpt`` 只识别 ``results`` / ``content`` 两个键，其他
    形状会直接以 JSON 呈现。这里按记录尽力读取名称与说明字段，未知形状同样以
    可读文本呈现，而不是退回固定套话。
    """

    if isinstance(payload, list):
        entries = [item for item in payload if isinstance(item, Mapping)]
    elif isinstance(payload, Mapping):
        nested = [
            value
            for value in payload.values()
            if isinstance(value, list) and any(isinstance(i, Mapping) for i in value)
        ]
        if nested:
            entries = [item for item in nested[0] if isinstance(item, Mapping)]
        else:
            entries = [payload]
    else:
        return None

    for entry in entries:
        bits = _readable_bits(entry)
        if bits:
            excerpt = "。".join(bits)
            if len(excerpt) > 360:
                excerpt = f"{excerpt[:357].rstrip()}…"
            return excerpt

    return f"已核对 {len(entries)} 条外部结果。" if entries else None


def _web_openable_url(url: str | None) -> str | None:
    """只返回读者可打开的链接：http(s) 原样返回，其余不返回。

    无法打开的深链直接丢弃，避免给出读者用不了的链接。
    """

    if not url:
        return None
    text = str(url).strip()
    if not text:
        return None
    if text.startswith(("http://", "https://")):
        return text
    return None


def _public_source_presentation(source: SourceRecord) -> tuple[str, str, str | None]:
    """把含审计字段的 SourceRecord 转成面向普通用户的来源文案。"""

    excerpt = source.public_excerpt.strip()
    canonical_url = source.canonical_url
    title = clean_public_source_title(
        source.title, excerpt, source_record_id=source.source_record_id
    )

    snapshot_result = source.snapshot.get("sanitized_result")
    structured_excerpt, result_url = (
        _payload_public_excerpt(snapshot_result)
        if excerpt.lstrip().startswith(("{", "["))
        else (None, None)
    )
    if not structured_excerpt:
        structured_excerpt, result_url = _json_public_excerpt(excerpt)
    if structured_excerpt:
        excerpt = structured_excerpt
        canonical_url = canonical_url or result_url
    if excerpt.lstrip().startswith(("{", "[")):
        try:
            payload = json.loads(excerpt)
        except (TypeError, json.JSONDecodeError):
            payload = source.snapshot.get("sanitized_result")
        rendered = _rendered_payload_excerpt(payload)
        excerpt = rendered or "已核对外部结果。"
    excerpt = clean_public_source_excerpt(excerpt)
    return title, excerpt, _web_openable_url(canonical_url)
