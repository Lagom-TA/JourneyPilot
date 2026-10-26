"""交付内容的来源展示。"""

from __future__ import annotations

from travel_agent.planning.research.evidence import SourceRecord
from typing import Any
from typing import Mapping
import json


_PAYLOAD_RESULT_KEYS = ("results", "content")


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


_APP_LINK_WEB_FORMS = {
    "amap": "https://ditu.amap.com/detail/{ident}",
}


def _web_openable_url(url: str | None) -> str | None:
    """只返回读者可打开的链接：http(s) 原样返回，已知应用深链转网页，其余不返回。

    无法转换的深链直接丢弃，避免给出打不开的链接。
    """

    if not url:
        return None
    text = str(url).strip()
    if not text:
        return None
    if text.startswith(("http://", "https://")):
        return text
    scheme, _, rest = text.partition("://")
    template = _APP_LINK_WEB_FORMS.get(scheme.lower())
    if not template:
        return None
    ident = rest.rsplit("/", 1)[-1].strip()
    return template.format(ident=ident) if ident else None


def _public_source_presentation(source: SourceRecord) -> tuple[str, str, str | None]:
    """把含审计字段的 SourceRecord 转成面向普通用户的来源文案。"""

    title = source.title
    excerpt = source.public_excerpt.strip()
    canonical_url = source.canonical_url
    lowered = title.lower()

    if " branch review match: " in lowered:
        entity_name = title.split(":", 1)[-1].strip()
        title = f"餐饮评价核验：{entity_name}"
    elif " place record: " in lowered:
        entity_name = title.split(":", 1)[-1].strip()
        title = f"地点资料：{entity_name}"
    elif " route: " in lowered:
        route_label = excerpt.split(" · ", 1)[0].strip()
        title = f"交通路线：{route_label}" if route_label else "交通路线"
    elif source.source_record_id.startswith("weather-source-"):
        title = "天气参考"

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
    return title, excerpt, _web_openable_url(canonical_url)
