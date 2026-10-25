"""Integrations routes service_days."""

from __future__ import annotations

from datetime import date
from typing import Iterable
import re


def nominal_service_day_conflict(
    line_names: Iterable[str | None], service_date: date
) -> bool:
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
        if (
            not weekend
            and "节假日" not in text
            and "holiday" not in text
            and (
                "双休日" in text or "周末" in text or re.search(r"\bweekends?\b", text)
            )
        ):
            return True
    return False
