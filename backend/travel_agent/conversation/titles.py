"""Conversation titles."""

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
    """The provider's own name for a place, or nothing.

    Deliberately **not** normalised.  ``东京都/東京都`` is the name OSM answers with, and
    a client-side rewrite (简繁归一 included) would be a second authority for a
    user-visible string that the itinerary, the map and the report all print from the
    provider.
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
    """``2026-08-05`` → ``8/5``.

    Month and day only: the year is the same on both ends of every trip this
    product plans (≤14 days), so printing it twice spends a third of the title
    on a constant.
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
    """``上海市 → 东京都/東京都 · 8/5–8/8``, or nothing when there is no trip.

    Nothing is returned unless a **destination** is known: an origin and a date
    range with no destination names no trip, and a bare date range names any
    trip at all — which is the defect this module exists to remove.
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
    """Name a session after its subject — the trip if there is one, else the ask."""

    shaped = trip_shaped_title(controlled_trip_identity)
    if shaped:
        return shaped[:TITLE_MAX_LEN]
    return _question_shaped_title(user_message)
