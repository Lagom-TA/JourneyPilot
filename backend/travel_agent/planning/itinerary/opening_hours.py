from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import datetime
import re


_CLOCK = r"(?<!\d)(\d{1,2})[:：](\d{2})(?!\d)"


_INTERVAL = re.compile(_CLOCK + r"\s*(?:-|–|—|至|~|～|to)\s*" + _CLOCK, re.I)


_DATE = r"\d{4}(?:-\d{1,2}-\d{1,2}|/\d{1,2}/\d{1,2}|年\d{1,2}月\d{1,2}日)"


_DATE_RANGE = re.compile(
    r"(" + _DATE + r")(?:\s*(?:至|到|~|～|–|—)\s*(" + _DATE + r"))?"
)


_WEEKDAY = r"(?:周|星期|礼拜)([一二三四五六日天])"


_WEEKDAYS = {name: index for index, name in enumerate("一二三四五六日")}


_WEEKDAYS["天"] = 6


_EN_WEEKDAYS = {
    name: index
    for index, name in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))
}


_EN_WEEKDAY_RE = re.compile(
    r"\b(mon(?:days?)?|tue(?:sdays?)?|wed(?:nesdays?)?|thu(?:rsdays?)?|fri(?:days?)?|sat(?:urdays?)?|sun(?:days?)?)\b",
    re.I,
)


_CLOSED = r"(?:闭馆|闭园|休馆|休园|休息(?!区|室|时间)|不开放|暂停开放|暂停营业|停止营业|closed)"


_CONDITIONAL = re.compile(r"除外|例外|另行|以.*为准|except|holiday|节假日", re.I)


_LAST_ENTRY = re.compile(
    r"(?:最后入场|最后入馆|最晚入场|最晚入馆|停止入场|停止入馆|停止检票|last\s+(?:entry|admission))"
    r"(?:时间)?\s*[:：]?\s*(?:为|at)?\s*"
    + _CLOCK
    + r"|"
    + _CLOCK
    + r"\s*(?:后)?\s*(?:停止入场|停止入馆|停止检票|最后入场|最后入馆)",
    re.I,
)


def _minutes(hour: str, minute: str, *, allow_midnight: bool = False) -> int | None:
    h, m = int(hour), int(minute)
    if h == 24 and m == 0 and allow_midnight:
        return 1440
    return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else None


def _date_value(value: str) -> date | None:
    numbers = [int(part) for part in re.findall(r"\d+", value)]
    try:
        return date(*numbers)
    except ValueError:
        return None


def _weekday_scope(value: str) -> set[int]:
    matches = list(re.finditer(_WEEKDAY, value))
    days = {_WEEKDAYS[match.group(1)] for match in matches}
    days.update(
        _EN_WEEKDAYS[match.group(1).lower()[:3]]
        for match in _EN_WEEKDAY_RE.finditer(value)
    )

    for match in re.finditer(
        _WEEKDAY + r"\s*(?:至|到|-|–|—)\s*(?:周|星期|礼拜)?([一二三四五六日天])", value
    ):
        first, last = (_WEEKDAYS[part] for part in match.groups())
        days.update(
            index % 7 for index in range(first, last + (7 if last < first else 0) + 1)
        )
    if "周末" in value:
        days.update({5, 6})
    if "工作日" in value:
        days.update(range(5))
    return days


def _scope_applies(prefix: str, day: date) -> bool:
    dates = list(_DATE_RANGE.finditer(prefix))
    if dates:
        matched = False
        for match in dates:
            first = _date_value(match.group(1))
            last = _date_value(match.group(2)) if match.group(2) else first
            if first is not None and last is not None and first <= day <= last:
                matched = True
        if not matched:
            return False
    weekdays = _weekday_scope(prefix)
    return not weekdays or day.weekday() in weekdays


@dataclass(frozen=True)
class OpeningRules:
    intervals: tuple[tuple[int, int], ...] = ()
    closed: bool = False
    last_entry_minutes: int | None = None


def opening_rules(value: str | None, day: date) -> OpeningRules:
    """提取适用于该日期的规则；无法识别的文本保持未知。"""
    text = value or ""
    intervals: list[tuple[int, int]] = []
    last_entries: list[int] = []
    closed = False
    for clause in re.split(r"[;；\n。]", text):
        for closure in re.finditer(_CLOSED, clause, re.I):
            prefix = clause[: closure.start()]
            scope = re.split(r"[,，()（）]", prefix)[-1]

            if not re.search(_DATE, scope) and not _weekday_scope(scope):
                scope = prefix
            suffix = clause[closure.end() :]
            if re.search(_DATE, suffix) or _weekday_scope(suffix):
                scope += " " + suffix
            if prefix.endswith("不") or re.search(r"\bnot\s+$", prefix, re.I):
                continue
            if (
                re.search(_CLOCK, scope)
                and not re.search(_DATE, scope)
                and not _weekday_scope(scope)
            ):
                continue
            if _CONDITIONAL.search(scope + suffix):
                continue
            if _scope_applies(scope, day):
                closed = True
        first_clock = re.search(_CLOCK, clause)
        prefix = clause[: first_clock.start()] if first_clock else clause
        if not _scope_applies(prefix, day):
            continue
        for match in _INTERVAL.finditer(clause):
            start = _minutes(*match.groups()[:2])
            end = _minutes(*match.groups()[2:], allow_midnight=True)
            if start is None or end is None or start == end:
                continue
            if end < start:
                end += 1440
            intervals.append((start, end))
        for match in _LAST_ENTRY.finditer(clause):
            parts = [part for part in match.groups() if part is not None]
            minute = _minutes(*parts, allow_midnight=True)
            if minute is not None:
                last_entries.append(minute)
    return OpeningRules(
        tuple(sorted(set(intervals))),
        closed,
        min(last_entries) if last_entries else None,
    )


def opening_window_violation(
    value: str | None,
    day: date,
    start: datetime | None,
    end: datetime | None,
) -> str | None:
    """返回已知的冲突；没有冲突或缺少运营信息时返回 None。"""
    rules = opening_rules(value, day)
    if rules.closed:
        return "published closed day"
    if start is None or end is None:
        return None
    if start.date() != day or end <= start:
        return "schedule must be ordered within its local day"
    start_minutes = (
        start - start.replace(hour=0, minute=0, second=0, microsecond=0)
    ).total_seconds() / 60
    end_minutes = start_minutes + (end - start).total_seconds() / 60
    if (
        rules.last_entry_minutes is not None
        and start_minutes >= rules.last_entry_minutes
    ):
        return "at or after the published last entry time"
    if rules.intervals and not any(
        opens <= start_minutes and end_minutes <= closes
        for opens, closes in rules.intervals
    ):
        return "outside the published opening window"
    return None
