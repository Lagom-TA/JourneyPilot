"""amap 坐标的 WGS-84 ⇄ GCJ-02 转换。

amap 使用 GCJ-02，地图投影与其他 OSM 地点身份使用 WGS-84，前端渲染 OSM 瓦片：
amap 坐标在合并前必须转换，WGS-84 坐标在作为 amap 查询前也必须转换。偏移只在
中国境内存在，:func:`within_china_coordinate_box` 使境外转换为空操作，与 amap
在境外的返回一致。

该坐标框也用于判断哪个路线 Provider 能回答请求。两个用途共用同一个框，避免维护
两份「是否中国」的定义。框是矩形而不是国界，因此包含邻国部分地区；对这两个用途
而言，这些区域正是 amap 有数据而全球公交聚合器没有数据的区域。
"""

from __future__ import annotations

import math
from typing import Any, Optional, Tuple

_GCJ_A = 6378245.0                    # 克拉索夫斯基椭球长半轴
_GCJ_EE = 0.00669342162296594323      # 第一偏心率平方


def within_china_coordinate_box(lng: float, lat: float) -> bool:
    """判断该点是否位于 GCJ-02 与 WGS-84 存在差异的矩形区域内。"""
    return 73.66 < lng < 135.05 and 3.86 < lat < 53.55


def _gcj_transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _gcj_transform_lng(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def _gcj_offset(lng: float, lat: float) -> Tuple[float, float]:
    """某一点的 GCJ-02 偏移，返回以度为单位的 ``(dlng, dlat)``。"""
    dlat = _gcj_transform_lat(lng - 105.0, lat - 35.0)
    dlng = _gcj_transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - _GCJ_EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_GCJ_A * (1 - _GCJ_EE)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (_GCJ_A / sqrtmagic * math.cos(radlat) * math.pi)
    return dlng, dlat


def wgs84_to_gcj02(lng: float, lat: float) -> Tuple[float, float]:
    """把一个 WGS-84 点转换为 amap 的 GCJ-02；境外点原样返回。"""
    if not within_china_coordinate_box(lng, lat):
        return lng, lat
    dlng, dlat = _gcj_offset(lng, lat)
    return lng + dlng, lat + dlat


def gcj02_to_wgs84(lng: float, lat: float) -> Tuple[float, float]:
    """把一个 amap GCJ-02 点转换为 WGS-84；境外点原样返回。"""
    if not within_china_coordinate_box(lng, lat):
        return lng, lat
    dlng, dlat = _gcj_offset(lng, lat)
    return lng - dlng, lat - dlat


def amap_location_to_wgs84(location: Any) -> Tuple[Optional[float], Optional[float]]:
    """把一个 amap ``"lng,lat"`` 字符串解析为 WGS-84 的 ``(latitude, longitude)``。"""
    if not isinstance(location, str) or "," not in location:
        return None, None
    lng_text, _, lat_text = location.partition(",")
    try:
        longitude = float(lng_text)
        latitude = float(lat_text)
    except ValueError:
        return None, None
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return None, None
    longitude, latitude = gcj02_to_wgs84(longitude, latitude)
    return latitude, longitude
