from __future__ import annotations

from travel_agent.planning.delivery.presentation import TRANSPORT_MODE_LABELS
from travel_agent.planning.delivery.presentation import endpoint_label
from travel_agent.planning.itinerary.models import DiningStop
from travel_agent.planning.itinerary.models import LodgingStay
from travel_agent.planning.itinerary.models import StructuredItineraryV2
from travel_agent.planning.itinerary.models import TransportLeg
from travel_agent.planning.itinerary.models import VisitStop
from typing import Optional
from typing import Sequence


MAX_TRIP_HIGHLIGHTS = 5


_MAX_NAMED_LONG_DISTANCE = 4


_MAX_VISITS = 4


_MAX_DINING = 3


_MAX_LODGING = 2


_LONG_DISTANCE_LABEL = "跨城交通"


_VISIT_LABEL = "主要景点"


_DINING_LABEL = "特色餐饮"


_LODGING_LABEL = "住宿"


def _unique(names: Sequence[str], *, limit: int) -> list[str]:
    """按行程顺序取前 ``limit`` 个去重后的非空名称。

    按时间顺序而非重要性排序：行程顺序是计划事实，这些实体本身不携带
    「最值得看」的判断。去重除了整洁，也因为前端以每行文本作为 React key，
    两行相同文本会冲突。
    """

    seen: list[str] = []
    for name in names:
        cleaned = name.strip()
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
        if len(seen) == limit:
            break
    return seen


def _long_distance_service(leg: TransportLeg) -> str:
    """按读者能对照车票的方式命名一段跨城交通。

    有车次时以车次开头，因为车票上印的是车次；没有时使用交通方式名称。
    端点带上车站代码，原因相同：同名车站在别处无法区分。
    """

    route = f"{endpoint_label(leg.from_endpoint)} → {endpoint_label(leg.to_endpoint)}"
    service = next(
        (
            segment.service_number or segment.line_name
            for segment in leg.segments
            if segment.service_number or segment.line_name
        ),
        None,
    )
    lead = (
        service.strip()
        if service and service.strip()
        else TRANSPORT_MODE_LABELS[leg.selected_mode]
    )
    return f"{lead} {route}"


def _long_distance_line(legs: Sequence[TransportLeg]) -> Optional[str]:
    long_distance = [leg for leg in legs if leg.transport_class == "long_distance"]
    if not long_distance:
        return None
    named = _unique(
        [_long_distance_service(leg) for leg in long_distance],
        limit=_MAX_NAMED_LONG_DISTANCE,
    )
    if not named:
        return None
    body = " · ".join(named)

    if len(long_distance) > len(named):
        body = f"{body}，共 {len(long_distance)} 段"
    return f"{_LONG_DISTANCE_LABEL}：{body}"


def _named_line(label: str, names: Sequence[str], *, limit: int) -> Optional[str]:
    picked = _unique(names, limit=limit)
    if not picked:
        return None
    return f"{label}：{'、'.join(picked)}"


def _lodging_line(stays: Sequence[LodgingStay]) -> Optional[str]:
    entries: list[str] = []
    for stay in stays:
        name = stay.name.strip()
        if not name:
            continue
        entry = f"{name}（{stay.nights} 晚）"
        if entry not in entries:
            entries.append(entry)
        if len(entries) == _MAX_LODGING:
            break
    if not entries:
        return None
    return f"{_LODGING_LABEL}：{'、'.join(entries)}"


def derive_trip_highlights(
    *,
    visits: Sequence[VisitStop],
    dining: Sequence[DiningStop],
    lodging: Sequence[LodgingStay],
    transport_legs: Sequence[TransportLeg],
) -> list[str]:
    """把整份行程归纳为至多 :data:`MAX_TRIP_HIGHLIGHTS` 行。

    排序保证前两行可独立使用：workspace 概览只展示这两行，跨城交通与行程
    主要围绕的地点正是旅行者了解行程的入口。四类内容都为空时返回空列表，
    调用方对空列表不渲染内容。
    """

    lines = [
        _long_distance_line(transport_legs),
        _named_line(_VISIT_LABEL, [stop.name for stop in visits], limit=_MAX_VISITS),
        _named_line(_DINING_LABEL, [stop.name for stop in dining], limit=_MAX_DINING),
        _lodging_line(lodging),
    ]
    return [line for line in lines if line][:MAX_TRIP_HIGHLIGHTS]


def with_derived_highlights(itinerary: StructuredItineraryV2) -> StructuredItineraryV2:
    """返回带有实体所隐含亮点的同一份行程。

    ``StructuredItineraryV2`` 无法像 ``cost_summary`` 那样为 ``highlights``
    设置默认值：推导需要读取 ``delivery_presentation`` 中的交通文案，而该模块
    导入了实体模块。因此通过构造器创建的行程会保留调用方传入的 highlights，
    包括空值；所有写入已有行程的代码都经过本函数补齐。
    """

    return itinerary.model_copy(
        update={
            "highlights": derive_trip_highlights(
                visits=itinerary.visit_stops,
                dining=itinerary.dining_stops,
                lodging=itinerary.lodging_stays,
                transport_legs=itinerary.transport_legs,
            )
        }
    )
