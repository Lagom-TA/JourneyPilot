"""Utils geography."""

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
    """Great-circle distance between two WGS-84 points, in kilometres."""

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
    """Great-circle km between a place and its destination, or ``None``.

    ``None`` means "not answerable", and every caller must treat that as *not a
    rejection*: half a coordinate pair, a bool posing as a number, or a
    destination the controlled identity never carried a point for are all cases
    where this rule has nothing to say.  A missing point must never read as
    "infinitely far away" — that would delete every candidate for a destination
    whose geocode is absent, which is a supply outage, not an out-of-scope stop.
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
