"""经纬度距离计算。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass
from typing import Optional
import math

from typing import Any


_EARTH_RADIUS_KM = 6371.0088


def haversine_km(
    latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float
) -> float:
    """两个 WGS-84 点之间的大圆距离，单位公里。"""

    phi_a = math.radians(latitude_a)
    phi_b = math.radians(latitude_b)
    delta_phi = math.radians(latitude_b - latitude_a)
    delta_lambda = math.radians(longitude_b - longitude_a)
    inner = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2) ** 2
    )

    return 2 * _EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(inner)))


def distance_from_destination_km(
    latitude: Any,
    longitude: Any,
    destination_latitude: Any,
    destination_longitude: Any,
) -> Optional[float]:
    """地点与目的地之间的大圆距离（公里），无法计算时返回 ``None``。

    ``None`` 表示「无法判断」，调用方不能把它当作拒绝：坐标缺一半、布尔值冒充
    数字、受控身份没有目的地坐标，都属于本规则无法判断的情况。缺少坐标不能读作
    「无限远」，否则会让所有候选因目的地缺少地理编码而被删除，而那是供应故障，
    不是超出范围。
    """
    values = []
    for value in (latitude, longitude, destination_latitude, destination_longitude):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        values.append(float(value))
    place_latitude, place_longitude, home_latitude, home_longitude = values
    if not (-90.0 <= place_latitude <= 90.0 and -90.0 <= home_latitude <= 90.0):
        return None
    if not (-180.0 <= place_longitude <= 180.0 and -180.0 <= home_longitude <= 180.0):
        return None
    return haversine_km(place_latitude, place_longitude, home_latitude, home_longitude)
