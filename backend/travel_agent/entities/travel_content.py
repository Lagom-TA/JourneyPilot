"""Traveller-facing reasons and preparation actions derived from stored plans.

These helpers never turn admission checks into a claim about travel quality or
turn a suggested visit into a reservation. They also handle older saved plans.
"""

from __future__ import annotations

import re
from datetime import timedelta

from travel_agent.planning.itinerary.models import (
    DiningStop,
    LodgingStay,
    TransportLeg,
    VisitStop,
)

from .planning_time_buffers import (
    planned_alighting_buffer_minutes,
    planned_boarding_buffer_minutes,
)

_INTERNAL_REASON_MARKERS = (
    "eligible_place_options", "candidate_id", "place_id", "provider",
    "selection_slot", "fact_assertion", "source_record", "research_packet",
    "受控目的地", "住宿责任", "过夜责任", "过夜住宿责任", "硬约束",
    "准入", "证据闭包", "实体身份", "已核验为真实具体实体",
    "责任段", "connector", " gap", "day_", "long_distance", "high_speed_rail",
)


def public_selection_text(value: str, *, fallback: str = "请结合当天安排选择，并在预订前核对日期与费用。") -> str:
    """Preserve useful authored clauses; replace internal-only prose honestly."""
    if not any(marker in value.casefold() for marker in _INTERNAL_REASON_MARKERS):
        return value.strip() or fallback
    clauses = re.split(r"[。；;\n]+", value.strip())
    readable = [
        clause.strip() for clause in clauses
        if clause.strip()
        and not any(marker in clause.casefold() for marker in _INTERNAL_REASON_MARKERS)
    ]
    return "；".join(readable) if readable else fallback


def candidate_reason_fallback(candidate: object, index: int) -> str:
    """Use existing location/schedule facts when a legacy reason is internal prose."""
    name = getattr(candidate, "property_name", None) or getattr(candidate, "branch_name", None) or getattr(candidate, "name", None)
    address = getattr(candidate, "address", None)
    if index == 0 and name and address:
        return f"{name}，地址：{address}。"
    if hasattr(candidate, "from_endpoint"):
        if index == 0:
            return f"连接 {candidate.from_endpoint.name} 与 {candidate.to_endpoint.name}。"
        if getattr(candidate, "duration_minutes", None) is not None:
            return f"路线参考时长 {candidate.duration_minutes} 分钟；出发前核对班次与路况。"
    if getattr(candidate, "nights", None):
        return f"计划住宿 {candidate.nights} 晚，预订前核对入住日期、房型与总价。"
    if getattr(candidate, "recommended_duration_minutes", None):
        return f"建议预留 {candidate.recommended_duration_minutes} 分钟，按当天到访情况调整。"
    return "预订或前往之前，核对当天营业安排和费用。"


def selection_reason(entity: object) -> str:
    """When no usable rationale exists, state the plan instead of inventing benefits."""
    if isinstance(entity, LodgingStay):
        fallback = f"计划在 {entity.name} 连住 {entity.nights} 晚；地址：{entity.address}。"
    elif isinstance(entity, DiningStop):
        fallback = f"计划在 {entity.name} 用餐，预留 {entity.duration_minutes} 分钟。"
    elif isinstance(entity, VisitStop):
        fallback = f"计划游览 {entity.name}，预留 {entity.duration_minutes} 分钟。"
    else:
        raise TypeError(f"unsupported selection reason: {type(entity).__name__}")
    return public_selection_text(entity.selection_reason, fallback=fallback)


def preparation_actions(entity: object) -> list[str]:
    """Actions are advice conditional on recorded facts, never invented booking rules."""
    if isinstance(entity, (VisitStop, DiningStop)):
        when = f"{entity.planned_start:%m月%d日 %H:%M}" if entity.planned_start else "计划到访时段"
        actions = []
        if entity.reservation_required is True:
            actions.append(f"提前向官方或商家查找覆盖 {when} 的可约时段，预约成功后按确认时段调整到访安排。")
        elif entity.reservation_required is None:
            actions.append(f"向官方或商家核对 {when} 是否需要预约；当前尚无预约规则依据。")
        if not entity.opening_window or any(word in entity.opening_window.casefold() for word in ("待确认", "未知", "unknown")):
            actions.append("出发前核对当天营业时间与最晚入场时间，再确认到访安排。")
        return actions
    if isinstance(entity, LodgingStay):
        if entity.availability_status == "unavailable":
            return ["当前住宿不可用，请先另选住宿，再调整入住与接驳安排。"]
        if entity.price_kind == "reference_estimate" or entity.availability_status == "needs_confirmation":
            return [f"预订前向酒店或预订平台核对 {entity.check_in_date:%m月%d日} 至 {entity.check_out_date:%m月%d日} 的房型、余房与含税总价；参考价不代表已锁定房间。"]
        return ["预订后核对订单中的入住日期、房型与取消条件，保存确认凭证。"]
    if isinstance(entity, TransportLeg):
        preparation = []
        if entity.transport_class == "flexible" and entity.lineage.lineage_kind == "authored_entity":
            allowance = (
                f"预留{entity.duration_minutes}分钟"
                if entity.duration_minutes is not None else "预留接驳时间"
            )
            preparation.append(
                f"本计划为这段接驳{allowance}，尚未取得地图路线确认；"
                "出发前请查询实际路线、路况与接车时间，并据此调整出发时间。"
            )
        service_markers = ("工作日", "双休日", "周末", "节假日")
        if any(
            any(marker in (segment.line_name or "") for marker in service_markers)
            for segment in entity.segments
        ):
            preparation.append(
                "这段路线包含限定运营日期的线路，请按运营方当日公告核实；"
                "节假日与调休安排可能不同，确认运营后再出发。"
            )
        if entity.transport_class == "long_distance" and entity.departure_at:
            minutes = planned_boarding_buffer_minutes(entity.selected_mode)
            at = entity.departure_at - timedelta(minutes=minutes)
            preparation.append(f"按本计划预留{minutes}分钟出发准备，建议{at:%H:%M}前抵达出发站点；这是规划余量，运营方要求更早时以其规定为准。")
            if entity.arrival_at:
                arrival_minutes = planned_alighting_buffer_minutes(entity.selected_mode)
                ready_at = entity.arrival_at + timedelta(minutes=arrival_minutes)
                preparation.append(f"抵达后另预留{arrival_minutes}分钟下车及出站，后续市内接驳按{ready_at:%H:%M}之后出发安排；这是规划余量，取行李或现场排队较久时需增加时间。")
            if (
                entity.arrival_at
                and entity.departure_at.date() == entity.arrival_at.date()
                and entity.departure_at.hour < 14
                and entity.arrival_at.hour >= 12
            ):
                preparation.append("这段长途交通占用午餐时段，请提前安排用餐或自备餐食，并核对车站或车上餐饮供应。")
        if entity.booking_status in {"required", "recommended"}:
            action = "购票" if entity.booking_status == "required" else "预订"
            return preparation + [f"提前向运营方核对班次日期、出发站点与余票后{action}，以订单为准。"]
        if entity.booking_status == "booked":
            return preparation + ["核对本人订单与本计划的日期、班次和站点是否一致；本计划不构成订票凭证。"]
        if entity.booking_status == "unknown" and entity.transport_class == "long_distance":
            return preparation + ["先向运营方核对班次、票价与购票要求，再确认这段交通。"]
        return preparation
    return []
