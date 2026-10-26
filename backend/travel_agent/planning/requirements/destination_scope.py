"""目的地范围判定。"""

from __future__ import annotations

from typing import Any
from typing import Iterable
from typing import Mapping
from typing import MutableMapping

from travel_agent.utils.geography import distance_from_destination_km


DESTINATION_DISTANCE_KEY = "destination_distance_km"


MAX_DESTINATION_DISTANCE_KM = 25.0


def is_within_destination(
    latitude: Any,
    longitude: Any,
    destination_latitude: Any,
    destination_longitude: Any,
    *,
    limit_km: float = MAX_DESTINATION_DISTANCE_KM,
) -> bool:
    """判断地点是否足够接近、可作为该目的地的自有站点。

    无法计算距离时按在范围内处理，原因见 :func:`distance_from_destination_km`：
    缺少坐标不应被读成超出范围。
    """
    distance = distance_from_destination_km(
        latitude, longitude, destination_latitude, destination_longitude
    )
    return distance is None or distance <= limit_km


def annotate_destination_distance(
    results: Iterable[MutableMapping[str, Any]],
    *,
    destination_latitude: Any,
    destination_longitude: Any,
) -> None:
    """写入每个地点相对于其检索目的地的距离。

    每一层向下传递服务端归一化地点记录时都同时持有地点与被检索的目的地，因此
    只有这一层能给出距离；下游直接读取该字段，不再重算，因为行程身份不会随工具
    信封一起传递。

    结果写进服务端归一化记录，属于证据而不是模型声明。任一端点缺失时不写入：
    距离无法计算与超出范围是两回事，合并会删掉地理编码失败目的地的全部候选。
    写入是幂等的，记录已有相同标注时不会产生两个值。
    """
    if destination_latitude is None or destination_longitude is None:
        return
    for place in results:
        distance = distance_from_destination_km(
            place.get("latitude"),
            place.get("longitude"),
            destination_latitude,
            destination_longitude,
        )
        if distance is not None:
            place[DESTINATION_DISTANCE_KEY] = round(distance, 3)


def destination_points(
    controlled_trip_identity: Mapping[str, Any] | None,
) -> dict[str, tuple[float, float]]:
    """省略坐标不完整的目的地，避免调用方将其当作可用坐标。"""
    destinations = (controlled_trip_identity or {}).get("destinations") or []
    points: dict[str, tuple[float, float]] = {}
    for item in destinations:
        if not isinstance(item, Mapping):
            continue
        place_id = str(item.get("place_id") or "")
        latitude, longitude = item.get("latitude"), item.get("longitude")
        if not place_id:
            continue
        if isinstance(latitude, bool) or isinstance(longitude, bool):
            continue
        if not isinstance(latitude, (int, float)) or not isinstance(
            longitude, (int, float)
        ):
            continue
        points[place_id] = (float(latitude), float(longitude))
    return points
