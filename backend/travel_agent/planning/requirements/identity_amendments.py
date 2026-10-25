"""Planning requirements identity amendments."""

from __future__ import annotations

from pydantic import Field
from travel_agent.planning.requirements.identity_contracts import _StrictInputModel
from typing import Literal
import re


LockedIdentitySlot = Literal[
    "origin",
    "destination",
    "trip_dates",
    "party",
    "accessibility",
]


class LockedIdentityIntent(_StrictInputModel):
    classification: Literal["change_requested", "preservation_asserted", "none"]
    changed_slots: set[LockedIdentitySlot] = Field(default_factory=set)
    preserved_slots: set[LockedIdentitySlot] = Field(default_factory=set)


_LOCKED_IDENTITY_SLOT_PATTERNS: dict[LockedIdentitySlot, re.Pattern[str]] = {
    "origin": re.compile(r"出发地|旅行出发城市|全程起点"),
    "destination": re.compile(r"目的地(?:顺序)?|途经目的地|到访城市"),
    "trip_dates": re.compile(
        r"行程日期|旅行日期|出发日期|返程日期|起止日期|日期"
        r"|出发时间|返程时间|行程时间|旅行时间|起止时间|出行时间|开始时间|结束时间"
    ),
    "party": re.compile(
        r"同行人数|同行人(?!的?无障碍)|成人人数?|儿童人数?|小孩人数?|老人人数?|老人同行|人数"
    ),
    "accessibility": re.compile(
        r"(?:(?:同行人|同行者|旅伴)的?(?:是否)?(?:需要)?)?无障碍(?:需求|要求)"
    ),
}


_LOCKED_IDENTITY_MUTATION = (
    r"(?:改|改变|改成|改为|换|更换|调整|变更|增加|减少|取消|新增|删掉|移除)"
)


_LOCKED_IDENTITY_SLOT_EXPR = (
    "(?:"
    + "|".join(pattern.pattern for pattern in _LOCKED_IDENTITY_SLOT_PATTERNS.values())
    + ")"
)


_PRESERVATION_JOINER = r"(?:、|和|与|及|以及|或|/|\s)+"


_PRESERVATION_VALUE = r"(?:不变|原样|原计划|照旧)"


_PRESERVATION_PATTERNS = (
    re.compile(
        rf"(?:在)?(?:不|不要|无需|无须|不能|禁止|别)(?:再)?{_LOCKED_IDENTITY_MUTATION}"
        r"(?:(?![。；;！？!?]).){0,80}?(?:的前提下|前提下|情况下|，|,|；|;|。|$)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:保持|维持)\s*{_LOCKED_IDENTITY_SLOT_EXPR}"
        rf"(?:{_PRESERVATION_JOINER}{_LOCKED_IDENTITY_SLOT_EXPR})*\s*{_PRESERVATION_VALUE}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"{_LOCKED_IDENTITY_SLOT_EXPR}"
        rf"(?:{_PRESERVATION_JOINER}{_LOCKED_IDENTITY_SLOT_EXPR})*\s*"
        rf"(?:(?:保持|维持)\s*{_PRESERVATION_VALUE}|照旧)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:保持|维持)(?:(?![。；;！？!?]).){{1,80}}?{_PRESERVATION_VALUE}",
        re.IGNORECASE,
    ),
)


_POSITIVE_CLAUSE_SPLIT = re.compile(
    r"[，,；;。！？!?：:\n]+|(?:但是|但|不过|然而|只调整|仅调整)"
)


_MUTATION_PREFIX_FILLER = (
    r"(?:(?:一下|重新|当前|本次|这次|一个|一位|一名|一处|一座|新的|"
    r"\d+[个位名处座]?|[一二三四五六七八九十]+[个位名处座]?)\s*){0,4}"
)


_TRIP_TIME_CHANGE = re.compile(
    rf"{_LOCKED_IDENTITY_MUTATION}(?:一下|成|到|为|至)?时间(?!表|安排|段|充裕|充足)"
    rf"|(?<!休息)(?<!开放)(?<!营业)(?<!就餐)(?<!用餐)时间{_LOCKED_IDENTITY_MUTATION}",
    re.IGNORECASE,
)


def _locked_identity_slots_in(text: str) -> set[LockedIdentitySlot]:
    return {
        slot
        for slot, pattern in _LOCKED_IDENTITY_SLOT_PATTERNS.items()
        if pattern.search(text)
    }


def _preservation_spans(text: str) -> list[re.Match[str]]:
    matches: list[re.Match[str]] = []
    for pattern in _PRESERVATION_PATTERNS:
        matches.extend(pattern.finditer(text))
    return sorted(matches, key=lambda match: (match.start(), match.end()))


def classify_locked_identity_intent(text: str) -> LockedIdentityIntent:
    """Classify locked identity edits without treating preservation as mutation.

    This deterministic guard never derives or mutates ``ControlledTripIdentity``;
    the persisted TripRun field remains the sole source of identity truth.
    """

    normalized = " ".join(text.strip().split())
    if not normalized:
        return LockedIdentityIntent(classification="none")

    preserved_slots: set[LockedIdentitySlot] = set()
    preservation_spans = _preservation_spans(normalized)
    for match in preservation_spans:
        preserved_slots.update(_locked_identity_slots_in(match.group(0)))

    positive_text = list(normalized)
    for match in preservation_spans:
        positive_text[match.start() : match.end()] = " " * (match.end() - match.start())
    positive = "".join(positive_text)

    changed_slots: set[LockedIdentitySlot] = set()
    for clause in _POSITIVE_CLAUSE_SPLIT.split(positive):
        clause = clause.strip()
        if not clause:
            continue
        for slot, slot_pattern in _LOCKED_IDENTITY_SLOT_PATTERNS.items():
            slot_expr = slot_pattern.pattern
            mutation = re.compile(
                rf"(?:把|将|请)?\s*(?:{slot_expr})\s*(?:要|需要|希望|想要|重新)?\s*"
                rf"{_LOCKED_IDENTITY_MUTATION}"
                rf"|{_LOCKED_IDENTITY_MUTATION}\s*{_MUTATION_PREFIX_FILLER}(?:{slot_expr})",
                re.IGNORECASE,
            )
            if mutation.search(clause):
                changed_slots.add(slot)

        if _TRIP_TIME_CHANGE.search(clause):
            changed_slots.add("trip_dates")

    classification: Literal["change_requested", "preservation_asserted", "none"]
    if changed_slots:
        classification = "change_requested"
    elif preservation_spans:
        classification = "preservation_asserted"
    else:
        classification = "none"
    return LockedIdentityIntent(
        classification=classification,
        changed_slots=changed_slots,
        preserved_slots=preserved_slots,
    )
