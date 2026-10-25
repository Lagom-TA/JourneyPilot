"""Planning requirements normalization clauses."""

from __future__ import annotations

from travel_agent.planning.requirements.intent_contracts import IntentImpactStage
from travel_agent.planning.requirements.intent_contracts import IntentKind
from travel_agent.planning.requirements.intent_contracts import IntentStrength
from travel_agent.planning.requirements.intent_contracts import IntentTarget
from travel_agent.planning.requirements.intent_contracts import IntentValue
from travel_agent.planning.requirements.intent_contracts import VerificationMode
from travel_agent.planning.requirements.normalization.contracts import IntentDraft
from travel_agent.planning.requirements.normalization.contracts import SourceClause
from typing import Dict
from typing import Iterable
from typing import List
import logging
import re


logger = logging.getLogger(__name__)


_BOUNDARY = re.compile(r"[^，,。；;！？!?\n]+")


_MATERIAL_CUES = (
    "要",
    "不要",
    "不能",
    "必须",
    "安排",
    "规划",
    "每天",
    "每个",
    "最多",
    "至少",
    "重点",
    "解释",
    "方案",
    "avoid",
    "must",
    "every",
    "at most",
    "at least",
)


def split_source_clauses(
    sources: Iterable[tuple[str, str, str]],
) -> List[SourceClause]:
    clauses: List[SourceClause] = []
    for source_ref_id, source_kind, text in sources:
        for match in _BOUNDARY.finditer(text or ""):
            raw = match.group(0)
            stripped = raw.strip()
            if not stripped:
                continue
            leading = len(raw) - len(raw.lstrip())
            start = match.start() + leading
            end = start + len(stripped)
            digest = _short_hash(source_ref_id, str(start), str(end), stripped)
            clauses.append(
                SourceClause(
                    clause_id=f"clause_{digest}",
                    source_ref_id=source_ref_id,
                    source_kind=source_kind,
                    source_text=stripped,
                    span_start=start,
                    span_end=end,
                )
            )
    return clauses


def is_material_clause(text: str) -> bool:
    lowered = text.lower()
    return any(cue in lowered for cue in _MATERIAL_CUES)


def _short_hash(*parts: str) -> str:
    from hashlib import sha256

    return sha256("\0".join(parts).encode("utf-8")).hexdigest()[:24]


def _intent(
    kind: IntentKind,
    target: IntentTarget,
    strength: IntentStrength,
    value: IntentValue,
    summary: str,
    impact_stages: List[IntentImpactStage],
    verification: VerificationMode,
) -> IntentDraft:
    return IntentDraft(
        kind=kind,
        target=target,
        strength=strength,
        priority=90 if strength is IntentStrength.HARD else 60,
        value=value,
        verification_mode=verification,
        impact_stages=impact_stages,
        public_summary=summary[:300],
    )


def _identity_tokens(identity: Dict[str, object]) -> List[str]:
    tokens: List[str] = []
    origin = identity.get("origin")
    if isinstance(origin, dict):
        tokens.extend(str(origin.get(key) or "") for key in ("name", "display_name"))
    for destination in identity.get("destinations") or []:
        if isinstance(destination, dict):
            tokens.extend(
                str(destination.get(key) or "") for key in ("name", "display_name")
            )
    tokens.extend(str(identity.get(key) or "") for key in ("start_date", "end_date"))
    return [token for token in tokens if token]


def _attributes(text: str) -> List[str]:
    return [
        value for value in ("安静", "无障碍", "亲子", "本地", "室内") if value in text
    ]


def _chinese_number(value: str) -> int:
    if value.isdigit():
        return int(value)
    return {
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }.get(value, 0)


def _target_for_text(text: str) -> IntentTarget:
    if any(token in text for token in ("咖啡", "餐", "美食", "早餐", "午餐", "晚餐")):
        return IntentTarget.DINING
    if any(token in text for token in ("酒店", "住宿", "房间", "民宿")):
        return IntentTarget.LODGING
    if any(
        token in text
        for token in ("高铁", "火车", "航班", "飞机", "去程", "返程", "往返")
    ):
        return IntentTarget.LONG_DISTANCE_TRANSPORT
    if any(token in text for token in ("交通", "地铁", "公交", "步行", "打车")):
        return IntentTarget.LOCAL_TRANSPORT
    return IntentTarget.VISIT
