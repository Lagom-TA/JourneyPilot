"""参考班次的交付文案。"""

from __future__ import annotations

from travel_agent.planning.research.reference_service_contracts import (
    ProviderReferenceService,
)
from typing import Optional


_LEG_ROLE_LABELS = {"outbound": "去程", "return": "返程"}


_CLAIM_LABELS = {
    "train_no": "车次",
    "departure_time": "出发时刻",
    "arrival_time": "到达时刻",
    "price": "票价",
    "inventory": "余票",
}


def _duration_clause(duration_minutes: Optional[int]) -> str:
    if not duration_minutes:
        return ""
    hours, minutes = divmod(int(duration_minutes), 60)
    if hours and minutes:
        return f"，约 {hours} 小时 {minutes} 分"
    if hours:
        return f"，约 {hours} 小时"
    return f"，约 {minutes} 分钟"


def _price_clause(price: Optional[float]) -> str:
    if price is None:
        return ""
    amount = int(price) if float(price).is_integer() else price
    return f"，最低票价 ¥{amount}"


def reference_service_note(service: ProviderReferenceService) -> str:
    """每个交付界面为参考班次统一使用的一句话。"""

    claims = "、".join(
        _CLAIM_LABELS.get(claim, claim) for claim in service.unconfirmed_claims
    )
    return (
        f"{_LEG_ROLE_LABELS[service.leg_role]}参考班次 {service.service_number}："
        f"{service.from_name} {service.departure_time} → "
        f"{service.to_name} {service.arrival_time}"
        f"{_duration_clause(service.duration_minutes)}"
        f"{_price_clause(service.lowest_observed_price_cny)}；"
        f"这是供应商在 {service.reference_date.isoformat()} 的真实班次，"
        f"未对 {service.requested_date.isoformat()} 确认的是{claims}，"
        "出行前请按实际出行日期重新核对。"
    )
