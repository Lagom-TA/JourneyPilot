"""交付内容中的选点理由与准备事项。"""

from __future__ import annotations

from datetime import timedelta
from travel_agent.planning.itinerary.models import DiningStop
from travel_agent.planning.itinerary.models import LodgingStay
from travel_agent.planning.itinerary.models import TransportLeg
from travel_agent.planning.itinerary.models import VisitStop
from travel_agent.planning.itinerary.time_buffers import (
    planned_alighting_buffer_minutes,
)
from travel_agent.planning.itinerary.time_buffers import planned_boarding_buffer_minutes
import re


_INTERNAL_REASON_MARKERS = (
    "eligible_place_options",
    "candidate_id",
    "place_id",
    "provider",
    "selection_slot",
    "fact_assertion",
    "source_record",
    "research_packet",
    "受控目的地",
    "住宿责任",
    "过夜责任",
    "过夜住宿责任",
    "硬约束",
    "准入",
    "证据闭包",
    "实体身份",
    "已核验为真实具体实体",
    "责任段",
    "connector",
    " gap",
    "day_",
    "long_distance",
    "high_speed_rail",
)


def public_selection_text(
    value: str, *, fallback: str = "请结合当天安排选择，并在预订前核对日期与费用。"
) -> str:
    """保留可读的作者理由；含内部术语的句子替换为通用说明。"""
    if not any(marker in value.casefold() for marker in _INTERNAL_REASON_MARKERS):
        return value.strip() or fallback
    clauses = re.split(r"[。；;\n]+", value.strip())
    readable = [
        clause.strip()
        for clause in clauses
        if clause.strip()
        and not any(marker in clause.casefold() for marker in _INTERNAL_REASON_MARKERS)
    ]
    return "；".join(readable) if readable else fallback


def candidate_reason_fallback(candidate: object, index: int) -> str:
    """理由不可读时，用候选自带的地址与时间信息生成说明。"""
    name = (
        getattr(candidate, "property_name", None)
        or getattr(candidate, "branch_name", None)
        or getattr(candidate, "name", None)
    )
    address = getattr(candidate, "address", None)
    if index == 0 and name and address:
        return f"{name}，地址：{address}。"
    if hasattr(candidate, "from_endpoint"):
        if index == 0:
            return (
                f"连接 {candidate.from_endpoint.name} 与 {candidate.to_endpoint.name}。"
            )
        if getattr(candidate, "duration_minutes", None) is not None:
            return f"路线参考时长 {candidate.duration_minutes} 分钟；出发前核对班次与路况。"
    if getattr(candidate, "nights", None):
        return f"计划住宿 {candidate.nights} 晚，预订前核对入住日期、房型与总价。"
    if getattr(candidate, "recommended_duration_minutes", None):
        return f"建议预留 {candidate.recommended_duration_minutes} 分钟，按当天到访情况调整。"
    return "预订或前往之前，核对当天营业安排和费用。"


def selection_reason(entity: object) -> str:
    """没有可用理由时陈述计划本身，不编造优点。"""
    if isinstance(entity, LodgingStay):
        fallback = (
            f"计划在 {entity.name} 连住 {entity.nights} 晚；地址：{entity.address}。"
        )
    elif isinstance(entity, DiningStop):
        fallback = f"计划在 {entity.name} 用餐，预留 {entity.duration_minutes} 分钟。"
    elif isinstance(entity, VisitStop):
        fallback = f"计划游览 {entity.name}，预留 {entity.duration_minutes} 分钟。"
    else:
        raise TypeError(f"unsupported selection reason: {type(entity).__name__}")
    return public_selection_text(entity.selection_reason, fallback=fallback)


def preparation_actions(entity: object) -> list[str]:
    """补充时间线和实体块没有呈现的行动信息。

    预约与开放时间已作为实体事实行展示，这里不再重复成段提醒。
    """
    if isinstance(entity, (VisitStop, DiningStop)):
        return []
    if isinstance(entity, LodgingStay):
        if entity.availability_status == "unavailable":
            return ["当前住宿不可用，需另选住宿。"]
        return []
    if isinstance(entity, TransportLeg):
        preparation = []
        service_markers = ("工作日", "双休日", "周末", "节假日")
        if any(
            any(marker in (segment.line_name or "") for marker in service_markers)
            for segment in entity.segments
        ):
            preparation.append("该线路只在限定日期运营，需按出行当天确认开行。")
        if entity.transport_class == "long_distance" and entity.departure_at:
            minutes = planned_boarding_buffer_minutes(entity.selected_mode)
            at = entity.departure_at - timedelta(minutes=minutes)
            preparation.append(
                f"建议{at:%H:%M}前抵达出发站点，预留{minutes}分钟进站。"
            )
            if entity.arrival_at:
                arrival_minutes = planned_alighting_buffer_minutes(entity.selected_mode)
                ready_at = entity.arrival_at + timedelta(minutes=arrival_minutes)
                preparation.append(
                    f"抵达后预留{arrival_minutes}分钟出站，接驳可安排在{ready_at:%H:%M}之后。"
                )
            if (
                entity.arrival_at
                and entity.departure_at.date() == entity.arrival_at.date()
                and entity.departure_at.hour < 14
                and entity.arrival_at.hour >= 12
            ):
                preparation.append(
                    "这段长途交通占用午餐时段，建议提前安排用餐或自备餐食。"
                )
        if entity.booking_status in {"required", "recommended"}:
            action = "购票" if entity.booking_status == "required" else "预订"
            return preparation + [f"提前{action}。"]
        if entity.booking_status == "booked":
            return preparation + ["按订单上的日期、班次和站点出行。"]
        return preparation
    return []
