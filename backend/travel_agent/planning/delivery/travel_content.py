"""交付内容中的选点理由与准备事项。"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Mapping, Sequence

from travel_agent.planning.itinerary.models import DiningStop
from travel_agent.planning.itinerary.models import LodgingStay
from travel_agent.planning.itinerary.models import TransportLeg
from travel_agent.planning.itinerary.models import VisitStop
from travel_agent.planning.itinerary.time_buffers import (
    planned_alighting_buffer_minutes,
)
from travel_agent.planning.itinerary.time_buffers import planned_boarding_buffer_minutes
import re


_DATE_ASSUMPTION = re.compile(
    r"(?<![\u4e00-\u9fff])"
    r"(?:(?:本行程的|该酒店的|该住宿的|本次查询的|酒店的|本次|当前|该|预计|拟定)\s*)?"
    r"(?:入住|退房|住宿|酒店|出发|旅行|出行|行程|查询)?日期\s*"
    r"(?:(?:仅|暂|目前|只是|均|都)\s*)?"
    r"(?:为|是|系|属于|作为|按)?\s*"
    r"(?:(?:仅|暂|目前|只是|均|都)\s*)?"
    r"(?:(?:本次|当前)的?)?(?:规划|查询|行程|暂定|临时|参考)?(?:的)?"
    r"(?:假设|暂定)(?:日期)?"
    r"(?=$|[^\u4e00-\u9fff]|但是|但|不过|然而|并且|同时|另外|且)"
)


def _tidy_removed_text(value: str) -> str:
    """移除片段遗留的空括号和分隔符，不改写保留的内容。"""
    text = re.sub(r"[（(]\s*[）)]", "", value)
    text = re.sub(r"([，,；;。.!！?？\n])\s*[,，、；;]+", r"\1", text)
    text = re.sub(r"[，,；;：:]\s*(?=[。.!！?？\n]|$)", "", text)
    if not text.strip(" \t\r\n，,、；;：:。.!！?？—–-·"):
        return ""
    return text.strip(" \t\r\n，,、；;：:—–-·")


def clean_date_assumption_text(value: str) -> str:
    """在已展示日期的住宿文案中移除日期假设，不删除房态或实际日期。"""
    text = value.strip()
    cleaned = _DATE_ASSUMPTION.sub("", text)
    if cleaned == text:
        return text
    cleaned = _tidy_removed_text(cleaned)
    if _DATE_ASSUMPTION.match(text.lstrip("（(")):
        cleaned = re.sub(
            r"^(?:但是|但|不过|然而|并且|同时|另外|且)[\s，,]*", "", cleaned
        )
    return cleaned


_LODGING_DATE_ASSUMPTION = re.compile(
    r"(?:入住|退房|住宿|酒店)(?:的)?日期\s*(?:(?:仅|暂|目前|只是|均|都)\s*)?"
    r"(?:为|是|系|属于|作为|按)?\s*(?:(?:仅|暂|目前|只是|均|都)\s*)?"
    r"(?:(?:本次|当前)的?)?(?:规划|查询|行程|暂定|临时|参考)?(?:的)?"
    r"(?:假设|暂定)"
)


_GENERIC_CHECK_REMINDER = re.compile(
    r"(?:出行|出发|预订|前往)前(?:请|需|建议)?(?:核对|确认)"
    r"(?:开放时间|营业时间|票价|门票价格|预约信息|营业安排|费用)"
    r"(?:[、，,和与及/](?:开放时间|营业时间|票价|门票价格|预约信息|营业安排|费用))*"
)


def public_trip_unresolved(items: Sequence[str]) -> list[str]:
    """排除独立的日期假设与泛泛核对提示，保留具体行程缺口。"""
    result = []
    for item in items:
        value = item.strip().rstrip("。；; \t\r\n")
        if not value:
            continue
        bare_value = re.sub(r"[（）()]", "", value)
        if not clean_date_assumption_text(bare_value):
            continue
        if _GENERIC_CHECK_REMINDER.fullmatch(value):
            continue
        if _LODGING_DATE_ASSUMPTION.search(item):
            item = clean_date_assumption_text(item)
        if item:
            result.append(item)
    return result


def public_trip_title(value: str) -> str:
    """隐藏标题中的日期说明，保留实际日期及其余标题。"""
    text = clean_date_assumption_text(value)
    cleaned = re.sub(r"参考日期\s*[:：]?\s*", "", text)
    if cleaned != text:
        cleaned = _tidy_removed_text(cleaned)
    return cleaned or "旅行计划"


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


def public_lodging_text(
    value: str, *, fallback: str = "请结合当天安排选择，并在预订前核对日期与费用。"
) -> str:
    """清理住宿选项的日期假设；没有剩余理由时不补充套话。"""
    cleaned = clean_date_assumption_text(value)
    if cleaned != value.strip():
        return public_selection_text(cleaned, fallback="")
    return public_selection_text(cleaned, fallback=fallback)


def public_lodging_reasons(reasons: list[str]) -> list[str]:
    return [cleaned for reason in reasons if (cleaned := public_lodging_text(reason))]


def public_lodging_details(details: Mapping[str, Any]) -> dict[str, Any]:
    """只清理报告中的住宿叙述字段，保留事实值与其他字段。"""
    result = dict(details)
    for key in ("node_summary", "selection_reason", "tradeoff"):
        if isinstance(value := result.get(key), str):
            result[key] = clean_date_assumption_text(value)
    for key in ("notes", "selection_reasons"):
        if isinstance(values := result.get(key), list):
            cleaned_values = []
            for value in values:
                cleaned = clean_date_assumption_text(value) if isinstance(value, str) else value
                if not isinstance(value, str) or cleaned:
                    cleaned_values.append(cleaned)
            result[key] = cleaned_values
    return result


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
    """保留可读理由；住宿无理由时留空，其余条目回退到计划事实。"""
    if isinstance(entity, LodgingStay):
        fallback = (
            f"计划在 {entity.name} 连住 {entity.nights} 晚；地址：{entity.address}。"
        )
        return public_lodging_text(entity.selection_reason, fallback=fallback)
    if isinstance(entity, DiningStop):
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
                f"建议 {at:%H:%M} 前抵达出发站点，预留 {minutes} 分钟进站。"
            )
            if entity.arrival_at:
                arrival_minutes = planned_alighting_buffer_minutes(entity.selected_mode)
                ready_at = entity.arrival_at + timedelta(minutes=arrival_minutes)
                preparation.append(
                    f"抵达后预留 {arrival_minutes} 分钟出站，接驳可安排在 {ready_at:%H:%M} 之后。"
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
