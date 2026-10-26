"""交付条目文案渲染。"""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from travel_agent.planning.costs.presentation import format_cny
from travel_agent.planning.delivery.travel_content import preparation_actions
from travel_agent.planning.itinerary.models import CustomBlock
from travel_agent.planning.itinerary.models import DiningStop
from travel_agent.planning.itinerary.models import LodgingStay
from travel_agent.planning.itinerary.models import TransportLeg
from travel_agent.planning.itinerary.models import VisitStop
from travel_agent.planning.transport import TransportEndpoint
from travel_agent.planning.transport import TransportMode
from travel_agent.planning.transport import TransportSegment
from typing import Any
from typing import Optional
from typing import Sequence


class DeliveryPresentationError(ValueError):
    """条目无法渲染为可信文案时抛出。"""


TRANSPORT_MODE_LABELS: dict[TransportMode, str] = {
    TransportMode.FLIGHT: "飞机",
    TransportMode.HIGH_SPEED_RAIL: "高铁",
    TransportMode.TRAIN: "火车",
    TransportMode.COACH: "长途巴士",
    TransportMode.FERRY: "轮渡",
    TransportMode.METRO: "地铁",
    TransportMode.BUS: "公交",
    TransportMode.TRAM: "有轨电车",
    TransportMode.TAXI: "出租车",
    TransportMode.RIDE_HAILING: "网约车",
    TransportMode.DRIVE: "自驾",
    TransportMode.BIKE: "骑行",
    TransportMode.WALK: "步行",
    TransportMode.OTHER: "其它交通",
}


BOOKING_LABELS: dict[str, str] = {
    "not_required": "无需预订",
    "recommended": "建议提前预订",
    "required": "需要提前预订",
    "booked": "需自行确认",
    "unknown": "暂无预订信息",
}


WEATHER_OBSERVED_SUFFIX = "观测"


WEATHER_HISTORICAL_LABEL = "历史天气数据"


def weather_freshness_text(
    *, weather_data_state: str, observed_at: Optional[datetime]
) -> Optional[str]:
    """各展示面的徽标统一显示的这一行。"""

    if weather_data_state == "historical":
        return WEATHER_HISTORICAL_LABEL
    if observed_at is None:
        return None
    return f"{observed_at:%m-%d %H:%M} {WEATHER_OBSERVED_SUFFIX}"


_VISIT_TYPE_LABELS = {
    "attraction": "景点",
    "experience": "体验",
    "culture": "文化",
    "shopping": "购物",
    "nature": "自然",
    "other": "其它",
}


_MEAL_TYPE_LABELS = {
    "breakfast": "早餐",
    "lunch": "午餐",
    "dinner": "晚餐",
    "snack": "小吃",
    "other": "其它",
}


_AVAILABILITY_LABELS = {
    "needs_confirmation": "需要确认",
    "unavailable": "不可用",
}


_RESERVATION_LABELS = {True: "需要预约", False: "无需预约"}


def _clock(value: Optional[datetime]) -> Optional[str]:
    """返回 Bundle 存储的本地墙钟时间，不转换为查看者时区。"""

    return None if value is None else value.strftime("%H:%M")


def _clock_text(value: Optional[str]) -> Optional[str]:
    """按原样返回存储的 ``HH:MM`` 入住/退房时间。"""

    if not value:
        return None
    candidate = value.split("T", 1)[-1]
    return candidate[:5] if len(candidate) >= 5 and candidate[2:3] == ":" else None


def _time_range(start: Optional[str], end: Optional[str]) -> Optional[str]:
    if start and end:
        return f"{start}–{end}"
    return start or end


def _date_time(value: Optional[datetime]) -> Optional[str]:
    """可能落在其他 Day 的时刻，因此同时标出日期。"""

    return None if value is None else f"{value.month}月{value.day}日 {value:%H:%M}"


def _day(value: Optional[Date]) -> Optional[str]:
    return None if value is None else value.isoformat()


def format_duration_minutes(minutes: Optional[int]) -> Optional[str]:
    if minutes is None or minutes < 0:
        return None
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, remainder = divmod(minutes, 60)
    return f"{hours} 小时 {remainder} 分钟" if remainder else f"{hours} 小时"


def _distance(meters: Optional[int]) -> Optional[str]:
    """不足一公里用米，其余用公里。

    全程用米会让长途段显示为六位数米数：数值正确，但该量级下读者不使用这个单位。
    """

    if meters is None:
        return None
    if meters < 1000:
        return f"{meters} 米"
    return f"{meters / 1000:.0f} 公里"


def _price(value: Optional[float]) -> Optional[str]:
    return None if value is None else format_cny(value)


def _row(label: str, value: Optional[str]) -> Optional[str]:
    return None if value is None else f"{label}：{value}"


def _rows(*items: Optional[str]) -> list[str]:
    return [item for item in items if item]


def _transfer_label(count: int) -> str:
    """``0`` 在所有展示面都写作「直达」，与路线卡片的说法一致。"""

    return f"{count} 次换乘" if count > 0 else "直达"


def endpoint_label(endpoint: TransportEndpoint) -> str:
    """用各展示面统一的方式命名端点。

    站点代码用于区分同名车站，也是读者核对车票的线索，因此与名称一起显示。
    """

    return (
        f"{endpoint.name} {endpoint.station_code}"
        if endpoint.station_code
        else endpoint.name
    )


def _has_service_identity(segment: TransportSegment) -> bool:
    return bool(
        segment.service_number
        or segment.line_name
        or segment.operator_name
        or segment.from_endpoint.station_code
        or segment.to_endpoint.station_code
    )


def _segment_lines(leg: TransportLeg) -> list[str]:
    """服务身份信息：车次/航班号、运营方、站点代码。

    单段直达也会显示该信息，因为上方事实行只有时刻、距离、换乘与预订。
    ``第 N 段`` 前缀、交通方式与分段耗时只在真正换乘时出现；没有任何服务身份的
    单段（步行或出租接驳）不渲染，避免重复标题里的 ``A → B``。
    """

    segments: Sequence[TransportSegment] = leg.segments
    transfers = len(segments) > 1
    if not transfers:
        segments = [item for item in segments if _has_service_identity(item)]
    lines: list[str] = []
    for index, segment in enumerate(segments, start=1):
        route = f"{endpoint_label(segment.from_endpoint)} → {endpoint_label(segment.to_endpoint)}"
        service = segment.service_number or segment.line_name
        if not transfers:
            head = f"{service} {route}" if service else route
            lines.append(
                f"{head} · {segment.operator_name}" if segment.operator_name else head
            )
            continue
        parts = [TRANSPORT_MODE_LABELS[segment.mode], route]
        if service:
            parts.append(service)
        if segment.operator_name:
            parts.append(segment.operator_name)
        duration = format_duration_minutes(segment.duration_minutes)
        if duration:
            parts.append(duration)
        cost = _price(segment.cost_cny)
        if cost:
            parts.append(cost)
        lines.append(f"第 {index} 段：{' · '.join(parts)}")
    return lines


def _visit(entity: VisitStop) -> dict[str, Any]:
    highlights = [item for item in entity.visit_highlights if item.strip()]
    return {
        "display_title": entity.name,
        "node_summary": highlights[0] if highlights else None,
        "node_role": "place",
        "transport_mode": None,
        "time_label": _time_range(
            _clock(entity.planned_start), _clock(entity.planned_end)
        ),
        "duration_label": format_duration_minutes(entity.duration_minutes),
        "price_label": _price(entity.estimated_cost_cny),
        "facts": _rows(
            _row("类型", _VISIT_TYPE_LABELS.get(entity.visit_type)),
            _row("开放", entity.opening_window),
            _row("预约", _RESERVATION_LABELS.get(entity.reservation_required)),
            _row("地址", entity.address),
        ),
        "notes": _rows(
            f"重点体验：{'、'.join(highlights)}" if highlights else None,
            *preparation_actions(entity),
        ),
        "segment_lines": [],
    }


def _dining(entity: DiningStop) -> dict[str, Any]:
    dishes = [item for item in entity.recommended_dishes if item.strip()]
    cuisines = [item for item in entity.cuisine_types if item.strip()]
    spend = _price(entity.average_spend_cny)
    return {
        "display_title": entity.name,
        "node_summary": dishes[0] if dishes else None,
        "node_role": "place",
        "transport_mode": None,
        "time_label": _time_range(
            _clock(entity.planned_start), _clock(entity.planned_end)
        ),
        "duration_label": format_duration_minutes(entity.duration_minutes),
        "price_label": None if spend is None else f"人均 {spend}",
        "facts": _rows(
            _row("餐次", _MEAL_TYPE_LABELS.get(entity.meal_type)),
            _row("菜系", "、".join(cuisines) if cuisines else None),
            _row("营业", entity.opening_window),
            _row("预约", _RESERVATION_LABELS.get(entity.reservation_required)),
            _row("地址", entity.address),
        ),
        "notes": _rows(
            f"推荐菜：{'、'.join(dishes)}" if dishes else None,
            *[f"用餐提醒：{item}" for item in entity.dining_reminders if item.strip()],
            *preparation_actions(entity),
        ),
        "segment_lines": [],
    }


def _lodging(entity: LodgingStay, projection_role: str) -> dict[str, Any]:
    reference = entity.price_kind == "reference_estimate"
    nightly = _price(entity.nightly_price_cny)
    total = _price(entity.total_price_cny)
    if projection_role == "check_out":
        return {
            "display_title": f"退房 · {entity.name}",
            "node_summary": None,
            "node_role": "departure",
            "transport_mode": None,
            "time_label": _clock_text(entity.check_out_time),
            "duration_label": None,
            "price_label": None,
            "facts": _rows(_row("退房", _day(entity.check_out_date))),
            "notes": [],
            "segment_lines": [],
        }
    check_in = projection_role == "check_in"
    return {
        "display_title": f"入住 · {entity.name}" if check_in else entity.name,
        "node_summary": entity.address if check_in else None,
        "node_role": "arrival" if check_in else "place",
        "transport_mode": None,
        "time_label": _clock_text(entity.check_in_time) if check_in else None,
        "duration_label": None,
        "price_label": (
            None
            if nightly is None
            else f"{'参考每晚约' if reference else '每晚'} {nightly}"
        ),
        "facts": _rows(
            _row("入住", _day(entity.check_in_date)),
            _row("退房", _day(entity.check_out_date)),
            _row("晚数", f"{entity.nights} 晚"),
            _row("房型", entity.room_type),
            None
            if total is None
            else f"{'参考整段约' if reference else '整段'}：{total}",
            _row("状态", _AVAILABILITY_LABELS.get(entity.availability_status)),
            _row("地址", entity.address),
        ),
        "notes": preparation_actions(entity),
        "segment_lines": [],
    }


def _transport(entity: TransportLeg, projection_role: str) -> dict[str, Any]:
    mode = TRANSPORT_MODE_LABELS[entity.selected_mode]
    route = f"{entity.from_endpoint.name} → {entity.to_endpoint.name}"
    if projection_role == "arrival":
        return {
            "display_title": f"{mode} · {route}",
            "node_summary": None,
            "node_role": "arrival",
            "transport_mode": entity.selected_mode.value,
            "time_label": _clock(entity.arrival_at),
            "duration_label": None,
            "price_label": None,
            "facts": _rows(_row("抵达", _date_time(entity.arrival_at))),
            "notes": [],
            "segment_lines": [],
        }
    return {
        "display_title": f"{mode} · {route}",
        "node_summary": None,
        "node_role": "departure" if projection_role == "departure" else "movement",
        "transport_mode": entity.selected_mode.value,
        "time_label": _time_range(
            _clock(entity.departure_at), _clock(entity.arrival_at)
        ),
        "duration_label": format_duration_minutes(entity.duration_minutes),
        "price_label": _price(entity.total_cost_cny),
        "facts": _rows(
            _row("出发", _date_time(entity.departure_at)),
            _row("抵达", _date_time(entity.arrival_at)),
            _row("距离", _distance(entity.distance_meters)),
            _row("换乘", _transfer_label(entity.transfer_count)),
            _row("预订", BOOKING_LABELS.get(entity.booking_status)),
        ),
        "notes": preparation_actions(entity),
        "segment_lines": _segment_lines(entity),
    }


def _custom(entity: CustomBlock) -> dict[str, Any]:
    return {
        "display_title": entity.title,
        "node_summary": entity.note or None,
        "node_role": "place",
        "transport_mode": None,
        "time_label": _time_range(
            _clock(entity.planned_start), _clock(entity.planned_end)
        ),
        "duration_label": format_duration_minutes(entity.duration_minutes),
        "price_label": None,
        "facts": [],
        "notes": [],
        "segment_lines": [],
    }


def block_presentation(
    entity: object, *, entry_id: str, projection_role: str
) -> dict[str, Any]:
    """一次渲染时间线条目的全部文案。

    ``entry_id`` 随文案返回：同一天可能包含同一实体的两个位置（跨夜交通的两半、
    住宿的入住与退房），渲染结果需要按位置而非按实体寻址。
    """

    if isinstance(entity, VisitStop):
        rendered = _visit(entity)
    elif isinstance(entity, DiningStop):
        rendered = _dining(entity)
    elif isinstance(entity, LodgingStay):
        rendered = _lodging(entity, projection_role)
    elif isinstance(entity, TransportLeg):
        rendered = _transport(entity, projection_role)
    elif isinstance(entity, CustomBlock):
        rendered = _custom(entity)
    else:
        raise DeliveryPresentationError(
            f"unsupported delivery entry: {type(entity).__name__}"
        )
    return {"entry_id": entry_id, **rendered}
