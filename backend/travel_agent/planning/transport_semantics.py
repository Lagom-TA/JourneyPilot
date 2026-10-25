"""Planning transport semantics."""

from __future__ import annotations

from typing import Iterable
from typing import Protocol


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
