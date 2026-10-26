"""Planning requirements normalization deterministic."""

from __future__ import annotations

from travel_agent.planning.requirements.constraints.extraction import deterministic_budget_constraints
from travel_agent.planning.requirements.intent_contracts import CategoryIntentValue
from travel_agent.planning.requirements.intent_contracts import IntentKind
from travel_agent.planning.requirements.intent_contracts import IntentStrength
from travel_agent.planning.requirements.intent_contracts import VerificationMode
from travel_agent.planning.requirements.normalization.clauses import _intent
from travel_agent.planning.requirements.normalization.contracts import IntentDraft
from travel_agent.planning.requirements.normalization.contracts import (
    NormalizedClauseDraft,
)
from travel_agent.planning.requirements.normalization.contracts import (
    NormalizedConstraintDraft,
)
from travel_agent.planning.requirements.normalization.contracts import (
    RequestContractNormalizationResult,
)
from travel_agent.planning.requirements.normalization.contracts import SourceClause
from travel_agent.planning.requirements.normalization.clauses import _target_for_text
from travel_agent.planning.requirements.request_contracts import ClauseDisposition
from typing import Dict
from typing import List
import json
import re


def _enforce_deterministic_constraints(
    result: RequestContractNormalizationResult,
    clauses: List[SourceClause],
) -> RequestContractNormalizationResult:
    """用确定性的预算抽取补充 fallback 草稿。

    该函数只处理 :func:`_fallback_normalization` 产出的草稿，不作用于模型结果。
    """

    normalized: List[NormalizedClauseDraft] = []
    for source, draft in zip(clauses, result.clauses):
        deterministic = deterministic_budget_constraints(source.source_text)
        non_budget = [
            item for item in draft.constraints if item.category != "budget_cap"
        ]
        if deterministic:
            constraints = [
                *non_budget,
                *[
                    NormalizedConstraintDraft.model_validate(item)
                    for item in deterministic
                ],
            ]
        else:
            source_text = source.source_text.casefold()
            constraints = [
                *non_budget,
                *[
                    item
                    for item in draft.constraints
                    if item.category == "budget_cap"
                    and (
                        item.params.amount is None
                        or any(cue in source_text for cue in _MONETARY_CUES)
                    )
                ],
            ]
        if constraints == draft.constraints:
            normalized.append(draft)
            continue
        disposition = draft.disposition
        reason_code = draft.reason_code
        if constraints and not draft.intents:
            disposition = ClauseDisposition.MAPPED_TO_CONSTRAINT
            reason_code = None
        normalized.append(
            draft.model_copy(
                update={
                    "constraints": constraints,
                    "disposition": disposition,
                    "reason_code": reason_code,
                }
            )
        )
    return RequestContractNormalizationResult(clauses=normalized)


_EXPLICIT_MUST_INCLUDE = re.compile(
    r"^(?:请)?(?:务必|必须|一定要)(?:在行程中)?"
    r"(?:安排|游览|参观|去|打卡)\s*(?P<values>.+)$",
    re.IGNORECASE,
)


_EXPLICIT_ITEM_SEPARATOR = re.compile(r"[、,，]+")


_MONETARY_CUES = (
    "预算",
    "费用",
    "花费",
    "开销",
    "人民币",
    "cny",
    "元",
    "块",
    "以内",
    "不超过",
    "不高于",
    "至多",
    "上限",
    "budget",
)


_ALTERNATIVE_REQUEST_CUES = (
    "备选方案",
    "备用方案",
    "替代方案",
    "alternative option",
    "backup option",
)


def _explicit_must_include_terms(text: str) -> list[str]:
    """从显式必去条款中拆出可独立执行的条目。

    ``、`` 与逗号在本合同中是无歧义的列表分隔符；中文 ``和`` 不拆分，因为它
    也可能是专有名称的一部分（例如「颐和园」）。
    """

    match = _EXPLICIT_MUST_INCLUDE.match(text.strip())
    if match is None:
        return []
    terms = [
        item.strip(" \t。；;！!？?")
        for item in _EXPLICIT_ITEM_SEPARATOR.split(match.group("values"))
    ]
    terms = [item for item in terms if item and len(item) <= 80]
    return list(dict.fromkeys(terms))


def _enforce_deterministic_intents(
    result: RequestContractNormalizationResult,
    clauses: List[SourceClause],
) -> RequestContractNormalizationResult:
    """在 fallback 路径把显式列出的必去项拆成独立 Intent。

    只处理确定性 fallback 草稿，模型返回的结果不经过这里。
    """

    normalized: List[NormalizedClauseDraft] = []
    for source, draft in zip(clauses, result.clauses):
        terms = _explicit_must_include_terms(source.source_text)
        if not terms:
            normalized.append(draft)
            continue
        preserved = [
            intent
            for intent in draft.intents
            if intent.kind not in {IntentKind.OBJECTIVE, IntentKind.MUST_INCLUDE}
        ]
        explicit = [
            _intent(
                IntentKind.MUST_INCLUDE,
                _target_for_text(term),
                IntentStrength.HARD,
                CategoryIntentValue(categories=[term]),
                f"必须安排{term}",
                ["research", "composition"],
                VerificationMode.MIXED,
            )
            for term in terms
        ]
        normalized.append(
            draft.model_copy(
                update={
                    "disposition": ClauseDisposition.MAPPED_TO_INTENT,
                    "reason_code": None,
                    "intents": _dedupe_drafts([*preserved, *explicit]),
                }
            )
        )
    return RequestContractNormalizationResult(clauses=normalized)


def _dedupe_drafts(items: List[IntentDraft]) -> List[IntentDraft]:
    unique: Dict[str, IntentDraft] = {}
    for item in items:
        key = json.dumps(
            item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
        )
        unique.setdefault(key, item)
    return list(unique.values())
