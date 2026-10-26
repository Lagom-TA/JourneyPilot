"""调研与编排共用的 Provider 失败分类；分类结果不构成证据。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from travel_agent.planning.research.failure_protocol import PREFIX_PROVIDER_CAPABILITY, PREFIX_PROVIDER_DETERMINISTIC, PREFIX_PROVIDER_EMPTY, PREFIX_PROVIDER_TRANSIENT

ProviderFailureCategory = Literal["deterministic", "transient", "incomplete"]


@dataclass(frozen=True)
class ProviderFailureClassification:
    category: ProviderFailureCategory
    reason_code: str


_QUERY_MISS_MARKERS = ("found no executable route",)
_TRANSIENT_MARKERS = (
    "timeout",
    "timed out",
    "connection",
    "temporarily",
    "rate limit",
    "rate-limit",
    "cuqps",
    "exceeded_the_limit",
    "429",
    "502",
    "503",
    "504",
    "service unavailable",
    "provider unavailable",
    "upstream",
)
_DETERMINISTIC_MARKERS = (
    "401",
    "403",
    "unauthorized",
    "forbidden",
    "authentication",
    "auth failed",
    "permission denied",
    "invalid parameter",
    "invalid params",
    "bad request",
    "400",
    "unsupported",
    "not supported",
    "invalid output schema",
    "response schema",
    "provider contract",
)
_EXPLICIT_EXTERNAL_FAILURE_MARKERS = (
    PREFIX_PROVIDER_EMPTY,
    PREFIX_PROVIDER_CAPABILITY,
    PREFIX_PROVIDER_TRANSIENT,
    PREFIX_PROVIDER_DETERMINISTIC,
    "provider error",
    "provider failed",
    "provider failure",
    "model error",
    "model failed",
    "model failure",
    "tool error",
    "tool call failed",
    "tool execution failed",
    "error executing tool",
)


def classify_provider_failure(value: object) -> ProviderFailureClassification:
    """归类外部或 Provider 失败，且不把失败文本当作证据。"""
    raw = str(value or "")
    text = raw.casefold()
    if text.startswith(PREFIX_PROVIDER_DETERMINISTIC):
        return ProviderFailureClassification(
            category="deterministic",
            reason_code="provider_deterministic_failure",
        )
    if text.startswith(PREFIX_PROVIDER_TRANSIENT):
        return ProviderFailureClassification(
            category="transient",
            reason_code="provider_transient_failure",
        )
    if text.startswith(PREFIX_PROVIDER_EMPTY):
        return ProviderFailureClassification(
            category="incomplete",
            reason_code="provider_empty_result",
        )
    if text.startswith(PREFIX_PROVIDER_CAPABILITY):
        return ProviderFailureClassification(
            category="incomplete",
            reason_code="provider_capability_declined",
        )
    if any(marker in text for marker in _DETERMINISTIC_MARKERS):
        return ProviderFailureClassification(
            category="deterministic",
            reason_code="provider_deterministic_failure",
        )
    if any(marker in text for marker in _TRANSIENT_MARKERS):
        return ProviderFailureClassification(
            category="transient",
            reason_code="provider_transient_failure",
        )
    if any(marker in text for marker in _QUERY_MISS_MARKERS):
        return ProviderFailureClassification(
            category="incomplete",
            reason_code="provider_empty_result",
        )
    return ProviderFailureClassification(
        category="incomplete",
        reason_code="provider_incomplete_result",
    )


def is_provider_or_model_failure(value: object) -> bool:
    """判断 worker 失败是否带有明确的外部或模型失败信号。"""
    text = str(value or "").casefold()
    if not text:
        return False
    return any(
        marker in text
        for marker in (
            *_DETERMINISTIC_MARKERS,
            *_TRANSIENT_MARKERS,
            *_QUERY_MISS_MARKERS,
            *_EXPLICIT_EXTERNAL_FAILURE_MARKERS,
        )
    )
