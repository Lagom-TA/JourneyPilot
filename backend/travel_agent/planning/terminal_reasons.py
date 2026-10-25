"""Planning terminal reasons."""

from __future__ import annotations

from travel_agent.planning.outcomes import InternalFailureClass


DELIVERY_INTEGRITY_REASON_PREFIX = "delivery_integrity"


DELIVERY_INTEGRITY_UNCLASSIFIED_FALLBACK_REASON = "delivery_integrity_failure"


def delivery_integrity_reason_code(failure_class: InternalFailureClass) -> str:
    """由失败分类造终态 reason code，例如 ``delivery_integrity_research_gap``。"""
    return f"{DELIVERY_INTEGRITY_REASON_PREFIX}_{failure_class.value}"
