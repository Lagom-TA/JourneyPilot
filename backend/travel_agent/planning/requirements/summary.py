"""旅行摘要卡。"""

from __future__ import annotations

from typing import Any, Dict, Iterable

from travel_agent.planning.delivery.summary_card_contracts import (
    TripSummaryCard,
    TripSummaryFact,
)
from travel_agent.planning.state import TravelAgentState


def _brief_dict(state: TravelAgentState) -> Dict[str, Any]:
    from travel_agent.planning.requirements.identity_contracts import ControlledTripIdentity

    if not state.controlled_trip_identity:
        return {}
    identity = ControlledTripIdentity.model_validate(state.controlled_trip_identity)
    return {
        "destination": " → ".join(
            item.name or item.display_name for item in identity.destinations
        ),
        "duration_days": identity.duration_days,
        "dates_assumed": identity.dates_assumed,
        "departure_city": identity.origin.name if identity.origin else "",
        "departure_city_status": "provided" if identity.origin else "deferred",
        "constraints": [],
        "travel_style": identity.style.primary if identity.style else "",
    }


def _as_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _as_labels(value: Any, limit: int = 5) -> list[str]:
    if isinstance(value, str):
        candidates: Iterable[Any] = value.replace("，", "、").split("、")
    elif isinstance(value, list):
        candidates = value
    else:
        candidates = []
    labels: list[str] = []
    for candidate in candidates:
        label = _as_text(candidate, 28)
        if label and label not in labels:
            labels.append(label)
        if len(labels) >= limit:
            break
    return labels


def build_trip_summary_card(brief: Dict[str, Any]) -> Dict[str, Any]:
    """不调用模型，把结构化行程事实投影为面向用户的摘要卡。"""
    destination = _as_text(brief.get("destination"), 40) or "本次旅行"
    duration_days = brief.get("duration_days")
    duration = (
        f"{duration_days} 天{'（日期暂定）' if brief.get('dates_assumed') else ''}"
        if isinstance(duration_days, int) and duration_days > 0
        else "行程天数待定"
    )
    departure_city = _as_text(brief.get("departure_city"), 40)
    departure_provided = brief.get("departure_city_status") == "provided" and bool(
        departure_city
    )
    if not departure_provided:
        departure_city = ""

    headline = (
        f"{departure_city} → {destination} · {duration}"
        if departure_provided
        else f"{destination} · {duration}"
    )
    facts: list[TripSummaryFact] = [
        TripSummaryFact(label="目的地", value=destination, state="confirmed"),
        TripSummaryFact(
            label="行程",
            value=duration,
            state="confirmed"
            if isinstance(duration_days, int) and duration_days > 0 and not brief.get("dates_assumed")
            else "default",
        ),
        TripSummaryFact(
            label="出发地",
            value=departure_city or "稍后决定",
            state="confirmed" if departure_provided else "deferred",
        ),
    ]
    budget = _as_text(brief.get("budget"), 40)
    if budget:
        facts.append(TripSummaryFact(label="预算", value=budget, state="confirmed"))

    priorities = _as_labels(brief.get("constraints")) or _as_labels(
        brief.get("travel_style")
    )
    if not priorities:
        priorities = ["路线顺路", "信息清晰"]

    summary = (
        f"从{departure_city}出发前往{destination}，根据你的旅行偏好安排交通、住宿和每日路线。"
        if departure_provided
        else f"目的地为{destination}；出发地稍后决定，先安排当地路线与住宿，再补充往返交通。"
    )
    current_focus = "正在根据旅行需求查询交通、住宿和沿途路线。"
    next_milestone = "核对主要交通与开放信息"

    return TripSummaryCard(
        headline=headline,
        summary=summary,
        facts=facts,
        priorities=priorities,
        current_focus=current_focus,
        next_milestone=next_milestone,
        compact_line=f"{headline} · 调研中",
        requires_user_confirmation=False,
    ).model_dump()


async def trip_summary_card_after_brief_node(state: TravelAgentState) -> Dict[str, Any]:
    return {"trip_summary_card": build_trip_summary_card(_brief_dict(state))}
