"""Tools manifest inference."""

from __future__ import annotations

from travel_agent.tools.gateway_contracts import ToolAuthBoundary
from travel_agent.tools.gateway_contracts import ToolManifest
from travel_agent.tools.gateway_contracts import ToolOperationSensitivity
from travel_agent.tools.gateway_contracts import ToolPermissionClass
from travel_agent.tools.gateway_contracts import ToolResultTrustPolicy
from typing import Any
from typing import Dict
from typing import Optional
import re


_SENSITIVE_OPERATION_RE = re.compile(
    r"(book|booking|reserve|reservation|pay|payment|purchase|submit|passport|visa|cancel|delete|order|ticket[_-]?buy|checkout|refund|证件|护照|签证|支付|付款|预订|订票|取消|退款)",
    re.IGNORECASE,
)


_WRITE_OPERATION_RE = re.compile(
    r"(\b(create|update|write|send|post|upload|modify|change|edit)\b|生成订单|提交|发送|更新|写入)",
    re.IGNORECASE,
)


_SEARCH_RE = re.compile(
    r"(search|fetch|query|lookup|find|web|duckduckgo|serper|搜索|查询)", re.IGNORECASE
)


_RETRIEVAL_TOOL_NAME_RE = re.compile(
    r"(search|scrape|crawl|fetch|extract|lookup|geocode|autocomplete|retrieve)",
    re.IGNORECASE,
)


def infer_tool_category(
    tool_name: str, *, server_name: Optional[str] = None, description: str = ""
) -> str:
    haystack = f"{tool_name} {server_name or ''} {description}".lower()

    retrieval_by_name = bool(
        _RETRIEVAL_TOOL_NAME_RE.search(f"{tool_name} {server_name or ''}")
    )
    if retrieval_by_name:
        if any(
            token in haystack
            for token in ("map", "weather", "direction", "train", "flight", "currency")
        ):
            return "data"
        return "search"
    if any(
        token in haystack
        for token in ("payment", "pay", "checkout", "refund", "支付", "付款", "退款")
    ):
        return "payment"
    if any(
        token in haystack
        for token in ("book", "booking", "reserve", "hotel", "ticket", "订票", "预订")
    ):
        return "booking"
    if any(
        token in haystack
        for token in ("passport", "visa", "identity", "id_card", "证件", "护照", "签证")
    ):
        return "identity"
    if any(token in haystack for token in ("cancel", "delete", "取消", "删除")):
        return "cancellation"
    if any(
        token in haystack
        for token in ("map", "weather", "direction", "train", "flight", "currency")
    ):
        return "data"
    if _SEARCH_RE.search(haystack):
        return "search"
    if "ask_user" in haystack or "internal" in haystack:
        return "internal"
    return "other"


def infer_tool_manifest(
    *,
    tool_name: str,
    description: str = "",
    source: str = "unknown",
    server_name: Optional[str] = None,
    manifest: Optional[ToolManifest | Dict[str, Any]] = None,
) -> ToolManifest:
    if isinstance(manifest, ToolManifest):
        return manifest
    if isinstance(manifest, dict):
        payload = dict(manifest)
        payload.setdefault("tool_name", tool_name)
        payload.setdefault("source", source)
        payload.setdefault("server_name", server_name)
        return ToolManifest(**payload)

    category = infer_tool_category(
        tool_name, server_name=server_name, description=description
    )
    haystack = f"{tool_name} {server_name or ''} {description}"

    is_read_only_retrieval = category in {"search", "data"}
    sensitive = (
        bool(_SENSITIVE_OPERATION_RE.search(haystack)) and not is_read_only_retrieval
    )
    write_like = (
        bool(_WRITE_OPERATION_RE.search(haystack)) and not is_read_only_retrieval
    )
    is_local = source == "local"

    permission = ToolPermissionClass.READ_ONLY
    sensitivity = ToolOperationSensitivity.LOW
    side_effecting = False
    irreversible = False
    auth_boundary = ToolAuthBoundary.NONE

    if sensitive:
        permission = ToolPermissionClass.TRANSACTIONAL
        sensitivity = ToolOperationSensitivity.IRREVERSIBLE
        side_effecting = True
        irreversible = True
        auth_boundary = ToolAuthBoundary.PROVIDER_OAUTH_REQUIRED
    elif write_like:
        permission = ToolPermissionClass.WRITE
        sensitivity = ToolOperationSensitivity.HIGH
        side_effecting = True
    elif source == "mcp":
        permission = ToolPermissionClass.EXTERNAL_READ
        sensitivity = ToolOperationSensitivity.MEDIUM
        auth_boundary = (
            ToolAuthBoundary.SERVER_MANAGED if server_name else ToolAuthBoundary.FUTURE
        )
    elif is_local:
        permission = ToolPermissionClass.READ_ONLY
        sensitivity = ToolOperationSensitivity.LOW

    trust_policy = (
        ToolResultTrustPolicy.TRUSTED_SUMMARY
        if is_local and category in {"internal", "other"}
        else ToolResultTrustPolicy.UNTRUSTED_SUMMARY
    )
    if sensitive:
        trust_policy = ToolResultTrustPolicy.QUARANTINE

    return ToolManifest(
        tool_name=tool_name,
        source=source,
        server_name=server_name,
        category=category,
        permission_class=permission,
        operation_sensitivity=sensitivity,
        auth_boundary=auth_boundary,
        allow_offline_fallback=category in {"search", "data", "booking", "other"},
        evidence_allowed=not sensitive,
        side_effecting=side_effecting,
        irreversible=irreversible,
        untrusted_content_policy=trust_policy,
    )
