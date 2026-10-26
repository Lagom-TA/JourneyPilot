"""会话标题。"""

from __future__ import annotations

from typing import Any
from typing import Mapping
from typing import Optional
from typing import Sequence


TITLE_MAX_LEN = 32


FALLBACK_TITLE = "新对话"


_MAX_NAMED_DESTINATIONS = 2


_ROUTE_ARROW = " → "


_DESTINATION_JOIN = "、"


_DATE_RANGE_DASH = "–"


def _place_name(place: Any) -> Optional[str]:
    """返回地点在数据源中的原始名称；没有名称时返回 None。

    不做归一化：``东京都/東京都`` 是 OSM 返回的名称，行程、地图与报告都直接使用
    该字符串，客户端改写会成为同一用户可见文案的第二个来源。
    """

    if not isinstance(place, Mapping):
        return None
    name = str(place.get("name") or "").strip()
    return name or None


def _destination_names(destinations: Any) -> list[str]:
    if not isinstance(destinations, Sequence) or isinstance(destinations, (str, bytes)):
        return []
    names: list[str] = []
    for entry in destinations:
        name = _place_name(entry)
        if name and name not in names:
            names.append(name)
    return names


def _destinations_label(names: Sequence[str]) -> Optional[str]:
    if not names:
        return None
    if len(names) <= _MAX_NAMED_DESTINATIONS:
        return _DESTINATION_JOIN.join(names)
    return f"{names[0]} 等 {len(names)} 地"


def _short_date(value: Any) -> Optional[str]:
    """``2026-08-05`` → ``8/5``。

    只保留月和日：本产品规划的行程都在 14 天以内，标题两端的年份相同。
    """

    text = str(value or "").strip()
    parts = text.split("-")
    if len(parts) != 3:
        return None
    try:
        month, day = int(parts[1]), int(parts[2])
    except ValueError:
        return None
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{month}/{day}"


def _date_range_label(identity: Mapping[str, Any]) -> Optional[str]:
    start = _short_date(identity.get("start_date"))
    end = _short_date(identity.get("end_date"))
    if start and end:
        return start if start == end else f"{start}{_DATE_RANGE_DASH}{end}"
    return start or end


def trip_shaped_title(identity: Optional[Mapping[str, Any]]) -> Optional[str]:
    """``上海市 → 东京都/東京都 · 8/5–8/8``；没有旅程信息时返回 None。

    只有知道目的地时才返回标题：只有出发地和日期范围无法指代具体旅程。
    """

    if not isinstance(identity, Mapping) or not identity:
        return None

    destinations = _destinations_label(_destination_names(identity.get("destinations")))
    if not destinations:
        return None

    origin = _place_name(identity.get("origin"))
    route = f"{origin}{_ROUTE_ARROW}{destinations}" if origin else destinations
    dates = _date_range_label(identity)
    return f"{route} · {dates}" if dates else route


def _question_shaped_title(user_message: str) -> str:
    text = (user_message or "").strip()
    if not text:
        return FALLBACK_TITLE
    if len(text) <= TITLE_MAX_LEN:
        return text
    return text[:TITLE_MAX_LEN] + "..."


def derive_session_title(
    *,
    user_message: str,
    controlled_trip_identity: Optional[Mapping[str, Any]] = None,
) -> str:
    """以会话主题命名：有旅程时使用旅程信息，否则使用用户问题。"""

    shaped = trip_shaped_title(controlled_trip_identity)
    if shaped:
        return shaped[:TITLE_MAX_LEN]
    return _question_shaped_title(user_message)
