from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 网页检索可互相替代，不能用网页文本冒充地点、班次或路线的结构化身份。
_FALLBACK_MAP: Dict[str, List[Tuple[str, str]]] = {
    "tavily_search": [("free_web_search", "destination_search")],
    "tavily_research": [("free_web_search", "destination_search")],
    "brave_web_search": [("free_web_search", "destination_search")],
    "firecrawl_search": [("free_web_search", "destination_search")],
    "firecrawl_scrape": [("free_web_search", "destination_search")],
}

_QUERY_TEXT_KEYS: Tuple[str, ...] = (
    "query",
    "keywords",
    "q",
    "search_query",
    "text",
    "name",
)

# 失败调用仍可能携带模型生成的未知参数，因此按键过滤，而非只检查工具 schema。
_NON_SEMANTIC_KEYS = frozenset(
    {
        "limit",
        "max_results",
        "offset",
        "page",
        "page_size",
        "radius",
        "include_raw_content",
        "include_answer",
        "include_images",
        "search_depth",
        "extract_depth",
        "topic",
        "format",
        "timeout",
        "id",
        "poi_id",
        "place_id",
        "destination_place_id",
        "osm_ids",
        "location",
        "lat",
        "lng",
        "latitude",
        "longitude",
        "destination_latitude",
        "destination_longitude",
        "country_code",
        "candidate_kind",
        "aliases",
    }
)


def _fallback_query_text(original_args: Dict) -> str:
    fragments: List[str] = []
    for key in _QUERY_TEXT_KEYS:
        value = original_args.get(key)
        if isinstance(value, str) and value.strip():
            fragments.append(value.strip())
    for key, value in original_args.items():
        name = str(key)
        if name in _QUERY_TEXT_KEYS or name.lower() in _NON_SEMANTIC_KEYS:
            continue
        if isinstance(value, str) and value.strip():
            fragments.append(value.strip())
    return " ".join(dict.fromkeys(fragments))


def _adapt_args_for_fallback(
    original_tool: str,
    fallback_tool: str,
    adapter_key: str,
    original_args: Dict,
) -> Dict:
    if fallback_tool == "free_web_search":
        query = _fallback_query_text(original_args)

        if adapter_key == "destination_search":
            query += " 旅游攻略 景点"

        return {"query": query.strip()}

    return original_args


def get_fallback_tool(tool_name: str) -> Optional[Tuple[str, str]]:
    fallbacks = _FALLBACK_MAP.get(tool_name)
    if not fallbacks:
        return None
    return fallbacks[0]


def build_fallback_args(
    original_tool: str,
    fallback_tool: str,
    adapter_key: str,
    original_args: Dict,
) -> Dict:
    return _adapt_args_for_fallback(original_tool, fallback_tool, adapter_key, original_args)
