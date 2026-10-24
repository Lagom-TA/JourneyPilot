"""Service changes, distinct from provider geometry and walking segments."""

from __future__ import annotations

from datetime import date
import re
from typing import Iterable, Protocol


class _ServiceSegment(Protocol):
    mode: object
    service_number: str | None
    line_name: str | None
    operator_name: str | None


_SERVICE_MODES = {
    "flight",
    "high_speed_rail",
    "train",
    "coach",
    "ferry",
    "metro",
    "bus",
    "tram",
}


def nominal_service_day_conflict(line_names: Iterable[str | None], service_date: date) -> bool:
    """Reject clearly incompatible weekday labels, without asserting a holiday calendar.

    A matching weekday is not proof of service: holidays and adjusted workdays
    still need operator confirmation. A conflicting label is insufficient
    evidence to select this route when an unrestricted alternative may exist.
    """
    weekend = service_date.weekday() >= 5
    for name in line_names:
        text = (name or "").casefold()
        if weekend and ("工作日" in text or re.search(r"\bweekdays?\b", text)):
            return True
        if not weekend and "节假日" not in text and "holiday" not in text and (
            "双休日" in text or "周末" in text or re.search(r"\bweekends?\b", text)
        ):
            return True
    return False


def count_service_transfers(segments: Iterable[_ServiceSegment]) -> int:
    """Count evidenced changes of boarded service, ignoring access/egress legs.

    Multiple provider segments can describe the same train or transit line. An
    unnamed segment of the same mode does not prove a change; retain the last
    known identity rather than inventing a transfer from that missing detail.
    """
    previous_mode: str | None = None
    previous_number: str | None = None
    previous_line: str | None = None
    previous_operator: str | None = None
    transfers = 0
    for segment in segments:
        mode = str(getattr(segment.mode, "value", segment.mode))
        if mode not in _SERVICE_MODES:
            continue
        number = (segment.service_number or "").strip().casefold() or None
        line = (segment.line_name or "").strip().casefold() or None
        operator = (segment.operator_name or "").strip().casefold() or None
        different_service = (
            number != previous_number
            if number is not None and previous_number is not None
            else line is not None
            and previous_line is not None
            and line != previous_line
        )
        changed = previous_mode is not None and (
            mode != previous_mode
            or different_service
            or (
                operator is not None
                and previous_operator is not None
                and operator != previous_operator
            )
        )
        if changed:
            transfers += 1
        if changed or previous_mode is None:
            previous_number = number
            previous_line = line
            previous_operator = operator
        else:
            previous_number = number or previous_number
            previous_line = line or previous_line
            previous_operator = operator or previous_operator
        previous_mode = mode
    return transfers
