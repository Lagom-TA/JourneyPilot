"""Planning requirements normalization fallback."""

from __future__ import annotations

from travel_agent.planning.requirements.intent_contracts import AlternativeIntentValue
from travel_agent.planning.requirements.intent_contracts import CadenceIntentValue
from travel_agent.planning.requirements.intent_contracts import CategoryIntentValue
from travel_agent.planning.requirements.intent_contracts import CountIntentValue
from travel_agent.planning.requirements.intent_contracts import IntentKind
from travel_agent.planning.requirements.intent_contracts import IntentStrength
from travel_agent.planning.requirements.intent_contracts import IntentTarget
from travel_agent.planning.requirements.intent_contracts import OutputRequirementValue
from travel_agent.planning.requirements.intent_contracts import ScalarIntentValue
from travel_agent.planning.requirements.intent_contracts import VerificationMode
from travel_agent.planning.requirements.normalization.clauses import _attributes
from travel_agent.planning.requirements.normalization.clauses import _chinese_number
from travel_agent.planning.requirements.normalization.clauses import _identity_tokens
from travel_agent.planning.requirements.normalization.clauses import _intent
from travel_agent.planning.requirements.normalization.clauses import is_material_clause
from travel_agent.planning.requirements.normalization.contracts import IntentDraft
from travel_agent.planning.requirements.normalization.contracts import (
    NormalizedClauseDraft,
)
from travel_agent.planning.requirements.normalization.contracts import (
    RequestContractNormalizationResult,
)
from travel_agent.planning.requirements.normalization.contracts import SourceClause
from travel_agent.planning.requirements.normalization.deterministic import (
    _ALTERNATIVE_REQUEST_CUES,
)
from travel_agent.planning.requirements.normalization.deterministic import (
    _dedupe_drafts,
)
from travel_agent.planning.requirements.normalization.deterministic import (
    _enforce_deterministic_constraints,
)
from travel_agent.planning.requirements.normalization.deterministic import (
    _enforce_deterministic_intents,
)
from travel_agent.planning.requirements.request_contracts import ClauseDisposition
from typing import Dict
from typing import List
from typing import Optional
import re

from travel_agent.planning.requirements.normalization.clauses import _target_for_text


def _fallback_normalization(
    clauses: List[SourceClause], controlled_identity: Dict[str, object]
) -> RequestContractNormalizationResult:
    """Build the minimum deterministic contract after model failure only."""

    fallback = RequestContractNormalizationResult(
        clauses=[_fallback_clause(item, controlled_identity) for item in clauses]
    )
    return _enforce_deterministic_constraints(
        _enforce_deterministic_intents(fallback, clauses), clauses
    )


def _fallback_clause(
    clause: SourceClause, controlled_identity: Dict[str, object]
) -> NormalizedClauseDraft:
    text = clause.source_text
    lowered = text.lower()
    identity_tokens = _identity_tokens(controlled_identity)
    mentions_identity = any(token and token in text for token in identity_tokens)

    if len(_fallback_explicit_domains(text)) > 1:
        return NormalizedClauseDraft(
            clause_id=clause.clause_id,
            disposition=ClauseDisposition.UNRESOLVED,
            reason_code="semantic_normalization_required",
        )

    intents: List[IntentDraft] = []
    if match := re.search(
        r"(?:每天|每日).{0,10}(?:最多|不超过)\s*(\d+)\s*(?:个|处|家)", text
    ):
        intents.append(
            _intent(
                IntentKind.QUANTITY,
                _target_for_text(text),
                IntentStrength.HARD,
                CountIntentValue(
                    operator="at_most", count=int(match.group(1)), unit="day"
                ),
                "每天主要安排数量受上限约束",
                ["composition"],
                VerificationMode.DETERMINISTIC,
            )
        )
    elif match := re.search(
        r"(?:每天|每日).{0,10}(?:至少)\s*(\d+)\s*(?:个|处|家)", text
    ):
        intents.append(
            _intent(
                IntentKind.QUANTITY,
                _target_for_text(text),
                IntentStrength.HARD,
                CountIntentValue(
                    operator="at_least", count=int(match.group(1)), unit="day"
                ),
                "每天主要安排数量有最低要求",
                ["research", "composition"],
                VerificationMode.DETERMINISTIC,
            )
        )
    if "每天" in text or "每日" in text:
        intents.append(
            _intent(
                IntentKind.CADENCE,
                _target_for_text(text),
                IntentStrength.HARD,
                CadenceIntentValue(
                    frequency="once_per_day",
                    time_window=_time_window(text),
                    required_attributes=_attributes(text),
                ),
                text,
                ["research", "composition"],
                VerificationMode.MIXED,
            )
        )
    if any(
        token in lowered for token in ("不要", "不去", "避开", "禁止", "avoid", "no ")
    ):
        intents.append(
            _intent(
                IntentKind.MUST_EXCLUDE,
                _target_for_text(text),
                IntentStrength.HARD,
                CategoryIntentValue(categories=[text]),
                text,
                ["research", "composition"],
                VerificationMode.MIXED,
            )
        )
    if any(token in text for token in ("重点", "主题", "摄影", "建筑", "文化")):
        intents.append(
            _intent(
                IntentKind.THEME,
                IntentTarget.VISIT,
                IntentStrength.SOFT,
                CategoryIntentValue(categories=[text]),
                text,
                ["research", "composition"],
                VerificationMode.SEMANTIC,
            )
        )
    if any(token in text for token in ("解释", "说明", "列出", "标注")):
        intents.append(
            _intent(
                IntentKind.OUTPUT_REQUIREMENT,
                _target_for_text(text),
                IntentStrength.HARD,
                OutputRequirementValue(required_field=text, applies_to="each_item"),
                text,
                ["projection"],
                VerificationMode.MIXED,
            )
        )
    if any(
        token in lowered
        for token in (
            "再来一套",
            "换一套",
            "换一批",
            "不同风格",
            "更小众",
            "小众一点",
            "another version",
            "different set",
            "more niche",
        )
    ):
        intents.append(
            _intent(
                IntentKind.DIVERSITY,
                IntentTarget.VISIT,
                IntentStrength.SOFT,
                ScalarIntentValue(value=text),
                "探索另一组同等合规的候选",
                ["research", "composition"],
                VerificationMode.DETERMINISTIC,
            )
        )
    if match := re.search(r"([二两三四五六七八九十\d]+)\s*套.{0,12}方案", text):
        count = _chinese_number(match.group(1))
        if count >= 2:
            intents.append(
                _intent(
                    IntentKind.ALTERNATIVES,
                    IntentTarget.DELIVERY,
                    IntentStrength.HARD,
                    AlternativeIntentValue(count=count),
                    text,
                    ["composition", "projection"],
                    VerificationMode.DETERMINISTIC,
                )
            )
    elif any(token in lowered for token in _ALTERNATIVE_REQUEST_CUES):
        intents.append(
            _intent(
                IntentKind.ALTERNATIVES,
                IntentTarget.DELIVERY,
                IntentStrength.HARD,
                AlternativeIntentValue(count=2),
                text,
                ["composition", "projection"],
                VerificationMode.DETERMINISTIC,
            )
        )
    if not intents and any(token in text for token in ("规划", "行程", "安排")):
        intents.append(
            _intent(
                IntentKind.OBJECTIVE,
                IntentTarget.TRIP,
                IntentStrength.HARD,
                ScalarIntentValue(value=text),
                text,
                ["research", "composition", "projection"],
                VerificationMode.MIXED,
            )
        )
    if intents:
        return NormalizedClauseDraft(
            clause_id=clause.clause_id,
            disposition=ClauseDisposition.MAPPED_TO_INTENT,
            intents=_dedupe_drafts(intents),
            constraints=[],
        )
    if mentions_identity:
        return NormalizedClauseDraft(
            clause_id=clause.clause_id,
            disposition=ClauseDisposition.CONTROLLED_IDENTITY,
        )
    if is_material_clause(text):
        return NormalizedClauseDraft(
            clause_id=clause.clause_id,
            disposition=ClauseDisposition.UNRESOLVED,
            reason_code="normalization_failed",
        )
    return NormalizedClauseDraft(
        clause_id=clause.clause_id,
        disposition=ClauseDisposition.BACKGROUND_CONTEXT,
    )


def _fallback_explicit_domains(text: str) -> set[IntentTarget]:
    """Identify only explicit domain nouns for conservative fallback safety."""

    domains: set[IntentTarget] = set()
    if any(token in text for token in ("咖啡", "餐", "美食", "早餐", "午餐", "晚餐")):
        domains.add(IntentTarget.DINING)
    if any(token in text for token in ("酒店", "住宿", "房间", "民宿")):
        domains.add(IntentTarget.LODGING)
    if any(
        token in text
        for token in ("高铁", "火车", "航班", "飞机", "去程", "返程", "往返")
    ):
        domains.add(IntentTarget.LONG_DISTANCE_TRANSPORT)
    if any(token in text for token in ("市内交通", "地铁", "公交", "步行", "打车")):
        domains.add(IntentTarget.LOCAL_TRANSPORT)
    return domains


def _time_window(text: str) -> Optional[str]:
    for value in (
        "上午",
        "中午",
        "下午",
        "傍晚",
        "晚上",
        "morning",
        "afternoon",
        "evening",
    ):
        if value in text.lower():
            return value
    return None
