"""Planning research destination scope."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from travel_agent.integrations.places.taxonomy import (
    provider_place_type_matches_candidate_kind,
)
from travel_agent.planning.requirements.product_policy import (
    destinations_are_cn_only,
    discovery_physical_candidate_kinds,
    required_physical_candidate_kinds,
)
from travel_agent.planning.research.destination.prompts import (
    DINING_OPTIONS_TEMPLATE,
    KNOWLEDGE_BASE_NOMINATION,
    NO_DINING_OPTIONS,
    TASK_TEMPLATE,
)

_NODE_NAME = "destination_researcher"


_SCOPED_DISCOVERY_TOOLS = (
    "free_web_search",
    "tavily_search",
    "brave_web_search",
    "firecrawl_search",
)


def scope_destination_gap_tools(
    available_tools: List[Dict[str, Any]],
    recommended_tools: List[str],
    *,
    scoped_retry: bool = False,
) -> List[Dict[str, Any]]:
    """Expose the small identity-research set directly for a scoped retry."""
    if not scoped_retry or not recommended_tools:
        return available_tools
    recommended_set = set(recommended_tools)
    scoped = [
        tool
        for tool in available_tools
        if tool.get("schema", {}).get("function", {}).get("name", "") in recommended_set
    ]
    global_identity = [
        tool
        for tool in scoped
        if tool.get("schema", {}).get("function", {}).get("name", "")
        == "global_place_search"
    ]
    if global_identity:
        scoped_by_name = {
            tool.get("schema", {}).get("function", {}).get("name", ""): tool
            for tool in scoped
        }
        discovery = next(
            (
                scoped_by_name[name]
                for name in _SCOPED_DISCOVERY_TOOLS
                if name in scoped_by_name
            ),
            None,
        )
        return [*global_identity, *([discovery] if discovery is not None else [])]
    return scoped or available_tools


def build_destination_boundaries(
    controlled_trip_identity: Dict[str, Any] | None,
) -> List[Dict[str, Any]]:
    """Project controlled destinations into the boundary shape workers query with."""
    return [
        {
            "destination_id": str(item.get("place_id") or ""),
            "name": str(item.get("name") or ""),
            "country_code": str(item.get("country_code") or "").casefold(),
            "latitude": item.get("latitude"),
            "longitude": item.get("longitude"),
        }
        for item in (controlled_trip_identity or {}).get("destinations", [])
        if isinstance(item, dict)
    ]


def collect_offered_dining_place_ids(
    authoritative_tool_results: List[Dict[str, Any]],
) -> List[str]:
    """Every restaurant the server put on this round's table."""
    place_ids: List[str] = []
    for envelope in authoritative_tool_results:
        if not isinstance(envelope, dict):
            continue
        payload = envelope.get("sanitized_result")
        results = payload.get("results") if isinstance(payload, dict) else None
        for item in results or []:
            if not isinstance(item, dict):
                continue
            place_id = item.get("place_id")
            provider_type = item.get("provider_place_type")
            if not isinstance(place_id, str) or not place_id:
                continue
            if place_id in place_ids or not isinstance(provider_type, str):
                continue
            if provider_place_type_matches_candidate_kind(provider_type, "dining"):
                place_ids.append(place_id)
    return place_ids


def build_destination_task_prompt(
    *,
    task_desc: str,
    user_query: str,
    rag_context_section: str,
    require_current_candidate: bool,
    offered_dining_place_ids: List[str],
    destination_boundaries: List[Dict[str, Any]] | None = None,
) -> str:
    """Keep an identity repair focused on provider-backed place records."""
    boundaries = json.dumps(destination_boundaries or [], ensure_ascii=False)
    if require_current_candidate:
        return f"""这是 Candidate Gate 发起的目的地候选身份定向补研，不是重新生成通用景点和餐饮清单。

当前任务：{task_desc}
用户原始需求仅用于理解旅行背景：{user_query}
受控目的地边界：{boundaries}

本轮硬性执行规则：
- 只补当前 gaps 指向的 Visit/Dining 候选身份字段。若 gap 只给出领域而没有具体实体名，先用唯一开放的网页发现工具找到 1 至 3 个与用户偏好匹配的真实门店/地点名称，再分别用 global_place_search 解析稳定身份；禁止拿“东京餐厅”等类别词直接撞地点 Provider 后就结束本轮。
- 海外或全球地点优先调用 global_place_search，候选身份必须来自其结果，并逐字使用受控目的地的 country_code；maps_text_search 只可保留国家码与目的地一致的结果。网页发现结果只能提供待解析的实体名，不能直接支持 place_id、Provider type/country 或正式 Candidate。
- place_id、provider_place_type 与 provider_country_code 必须逐字来自本轮外部工具原始结果，并由对应 FactAssertion 和 SourceRecord.snapshot 支持；禁止拼接、归一化、猜测或输出 ChIJ placeholder 等自产标识。
- DiningCandidate 必须是具体餐馆、咖啡馆、酒吧或摊位门店；市场、商圈、美食街、区域和餐饮类别不能冒充门店候选。
- 网页搜索可用于交叉核验名称、地址和营业信息，但网页只出现名称或地址时不能作为 place_id 证据。
- 动态保留 1 至 6 个身份完整且质量足够的候选；宁可减少候选，也不得用 unknown、未检索、占位值或自产 evidence 凑数。
- 没有任何满足合同的候选就明确失败，不得放宽硬约束。
"""

    dining_section = DINING_OPTIONS_TEMPLATE.format(
        place_ids="、".join(offered_dining_place_ids) or NO_DINING_OPTIONS,
    )

    knowledge_base_section = (
        f"{rag_context_section}\n\n{KNOWLEDGE_BASE_NOMINATION}"
        if rag_context_section.strip()
        else rag_context_section
    )
    return (
        TASK_TEMPLATE.format(
            task_desc=task_desc,
            user_query=user_query,
            rag_context_section=knowledge_base_section,
        )
        + f"\n受控目的地边界：{boundaries}。所有地点必须保留 Provider 原始国家码并与对应 destination_id 一致。"
        + f"\n{dining_section}"
    )


def dining_intent_in_request(
    task_desc: str,
    user_query: str,
    controlled_trip_identity: Dict[str, Any],
) -> bool:
    """Did this round's request text or interests ask about food at all?"""
    style = controlled_trip_identity.get("style")
    interests = style.get("secondary_interests") if isinstance(style, dict) else []
    normalized_interests = {
        str(interest).strip().casefold()
        for interest in (interests or [])
        if str(interest).strip()
    }
    if normalized_interests.intersection(
        {"food", "dining", "ramen", "美食", "餐饮", "拉面"}
    ):
        return True
    request_text = f"{task_desc} {user_query}".casefold()
    return any(
        token in request_text
        for token in (
            "restaurant",
            "dining",
            "ramen",
            "美食",
            "餐馆",
            "餐厅",
            "拉面",
            "拉麵",
        )
    )


def dining_is_required_by_request(
    task_desc: str,
    user_query: str,
    controlled_trip_identity: Dict[str, Any],
) -> bool:
    """The second promise source, under the same country gate as the product one."""
    if not dining_intent_in_request(task_desc, user_query, controlled_trip_identity):
        return False
    return destinations_are_cn_only(controlled_trip_identity)


def resolve_required_candidate_kinds(
    assignment_required_kinds: List[str] | None,
    *,
    task_desc: str,
    user_query: str,
    controlled_trip_identity: Dict[str, Any],
) -> List[str] | None:
    """Return the *enforced* domains: what this packet must contain to be valid."""
    if assignment_required_kinds:
        return list(dict.fromkeys(assignment_required_kinds))
    required = required_physical_candidate_kinds(controlled_trip_identity)
    if dining_is_required_by_request(
        task_desc,
        user_query,
        controlled_trip_identity,
    ):
        required = required | {"dining"}
    return sorted(required) or None


def resolve_discovery_candidate_kinds(
    assignment_required_kinds: List[str] | None,
    *,
    task_desc: str,
    user_query: str,
    controlled_trip_identity: Dict[str, Any],
) -> List[str] | None:
    """Return the domains the deterministic preflight *tries* to ground."""
    if assignment_required_kinds:
        return list(dict.fromkeys(assignment_required_kinds))
    discovery = discovery_physical_candidate_kinds(controlled_trip_identity)
    if dining_intent_in_request(task_desc, user_query, controlled_trip_identity):
        discovery = discovery | {"dining"}
    return sorted(discovery) or None
