from __future__ import annotations

from dataclasses import dataclass
from travel_agent.planning.itinerary.models import StructuredItineraryV2
from travel_agent.planning.references import EntityType
from travel_agent.planning.research.evidence import FactAssertion
from travel_agent.utils.geography import haversine_km
from typing import Mapping
from typing import Optional
from typing import Sequence


LOCAL_TRANSPORT_CLASSES = frozenset({"public_transit", "flexible"})


@dataclass(frozen=True)
class DispersionLeg:
    """一天中的一段交通，只保留计算所需的两个字段。"""

    transport_class: str
    duration_minutes: Optional[int] = None


@dataclass(frozen=True)
class DayDispersion:
    """一天的活动强度测量，除两个数值外同时记录计数。

    ``local_leg_count`` / ``untimed_local_leg_count`` 与
    ``located_point_count`` / ``point_count`` 用于避免把小数值误读为良好：
    三段共 30 分钟与三段中仅一段计时 30 分钟不同；七个停留点中只有两个有坐标
    时，2 公里的跨度也不代表行程紧凑。
    """

    local_leg_minutes: int
    local_leg_count: int
    untimed_local_leg_count: int
    span_km: Optional[float]
    farthest_pair: Optional[tuple[str, str]]
    located_point_count: int
    point_count: int


def day_dispersion(
    points: Sequence[DispersionPoint], legs: Sequence[DispersionLeg]
) -> DayDispersion:
    """根据停留点与交通段测量一天。

    没有时长的交通段只计数，不按 0 分钟累加：时长未知与瞬时到达是不同事实。
    没有坐标的停留点同样不参与跨度计算，只计入未定位数量。
    """

    local = [leg for leg in legs if leg.transport_class in LOCAL_TRANSPORT_CLASSES]
    timed = [leg.duration_minutes for leg in local if leg.duration_minutes is not None]

    located = [point for point in points if point.is_located]
    span_km: Optional[float] = None
    farthest_pair: Optional[tuple[str, str]] = None
    for index, left in enumerate(located):
        for right in located[index + 1 :]:
            distance = haversine_km(
                float(left.latitude),
                float(left.longitude),
                float(right.latitude),
                float(right.longitude),
            )
            if span_km is None or distance > span_km:
                span_km = distance
                farthest_pair = (left.label, right.label)

    return DayDispersion(
        local_leg_minutes=sum(timed),
        local_leg_count=len(local),
        untimed_local_leg_count=len(local) - len(timed),
        span_km=span_km,
        farthest_pair=farthest_pair,
        located_point_count=len(located),
        point_count=len(points),
    )


def entity_coordinates(
    entity: object, fact_index: Mapping[str, FactAssertion]
) -> tuple[Optional[float], Optional[float]]:
    """返回停留点坐标，来源只有两层。

    撰写条目把地点 Provider 解析出的坐标直接放在停留点上；候选落位不设置
    坐标，其位置来自来源中已验证的坐标事实。地图投影与其他读取该位置的代码
    都使用这一规则，没有第三个来源，也不做推断。
    """

    latitude = getattr(entity, "latitude", None)
    longitude = getattr(entity, "longitude", None)
    if latitude is not None and longitude is not None:
        return latitude, longitude
    lineage = getattr(entity, "lineage", None)
    assertion_ids = getattr(lineage, "fact_assertion_ids", ())
    return verified_coordinate_pair(assertion_ids, fact_index)


def itinerary_dispersion(
    itinerary: StructuredItineraryV2, fact_index: Mapping[str, FactAssertion]
) -> list[tuple[str, DayDispersion]]:
    """按天顺序测量已物化行程的每一天。

    当天的时间线决定实体归属：实体落在它被投影到的那一天，接驳也按这一天构建。
    """

    stops: dict[str, object] = {}
    for stop in itinerary.visit_stops:
        stops[stop.item_id] = stop
    for stop in itinerary.dining_stops:
        stops[stop.item_id] = stop
    for stay in itinerary.lodging_stays:
        stops[stay.stay_id] = stay
    legs = {leg.transport_leg_id: leg for leg in itinerary.transport_legs}

    measured: list[tuple[str, DayDispersion]] = []
    for day in itinerary.day_plans:
        points: list[DispersionPoint] = []
        day_legs: list[DispersionLeg] = []
        for entry in day.timeline:
            if entry.entity_type == EntityType.TRANSPORT_LEG:
                leg = legs.get(entry.entity_id)
                if leg is not None:
                    day_legs.append(
                        DispersionLeg(
                            transport_class=leg.transport_class,
                            duration_minutes=leg.duration_minutes,
                        )
                    )
                continue
            stop = stops.get(entry.entity_id)
            if stop is None:
                continue
            latitude, longitude = entity_coordinates(stop, fact_index)
            points.append(
                DispersionPoint(
                    label=getattr(stop, "name", entry.entity_id),
                    latitude=latitude,
                    longitude=longitude,
                )
            )
        measured.append((day.day_id, day_dispersion(points, day_legs)))
    return measured


@dataclass(frozen=True)
class DispersionPoint:
    """一天中的一个停留点，携带能解析到的坐标。"""

    label: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @property
    def is_located(self) -> bool:
        return self.latitude is not None and self.longitude is not None


def verified_coordinate_pair(
    assertion_ids: Sequence[str], fact_index: Mapping[str, FactAssertion]
) -> tuple[Optional[float], Optional[float]]:
    """返回实体来源中已验证的经纬度，缺一时返回 (None, None)。

    只有单个坐标不构成位置。
    """

    values: dict[str, float] = {}
    for assertion_id in assertion_ids:
        fact = fact_index.get(assertion_id)
        if (
            fact is None
            or fact.status != "verified"
            or fact.field_path not in {"latitude", "longitude"}
        ):
            continue
        value = fact.asserted_value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        coordinate = float(value)
        if fact.field_path == "latitude" and -90 <= coordinate <= 90:
            values["latitude"] = coordinate
        if fact.field_path == "longitude" and -180 <= coordinate <= 180:
            values["longitude"] = coordinate
    if set(values) != {"latitude", "longitude"}:
        return None, None
    return values["latitude"], values["longitude"]
