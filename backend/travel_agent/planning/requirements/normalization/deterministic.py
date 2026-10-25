"""Planning requirements normalization deterministic."""

from __future__ import annotations

from travel_agent.panels.constraint import deterministic_budget_constraints
from travel_agent.planning.requirements.intent_contracts import AlternativeIntentValue
from travel_agent.planning.requirements.intent_contracts import CategoryIntentValue
from travel_agent.planning.requirements.intent_contracts import IntentKind
from travel_agent.planning.requirements.intent_contracts import IntentStrength
from travel_agent.planning.requirements.intent_contracts import IntentTarget
from travel_agent.planning.requirements.intent_contracts import VerificationMode
from travel_agent.planning.requirements.normalization.clauses import _intent
from travel_agent.planning.requirements.normalization.clauses import is_material_clause
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
    """Restore numeric constraints in the deterministic fallback path.

    This function is never applied to a valid model result.  It only hardens the
    fallback drafts built by :func:`_fallback_normalization` after the model call,
    schema validation, or contract validation has failed.
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
    """Return independently enforceable items from an explicit include clause.

    ``、`` and commas are unambiguous list separators in this contract.  Plain
    Chinese ``和`` is deliberately not split because it is also part of proper
    names such as ``颐和园``.
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


def _validate_model_contract(
    result: RequestContractNormalizationResult,
    clauses: List[SourceClause],
) -> None:
    """Reject a structurally valid model answer that violates source invariants.

    This validator never authors or rewrites an intent.  Semantic normalization
    belongs to the model; these checks only protect exact numeric constraints and
    explicit delivery flags whose omission would make later verification
    impossible.  Named-item parsing is deliberately absent here: syntax rules
    may assist the final fallback, but they do not overrule a valid LLM mapping.
    """

    for source, draft in zip(clauses, result.clauses):
        if is_material_clause(source.source_text) and draft.disposition in {
            ClauseDisposition.BACKGROUND_CONTEXT,
            ClauseDisposition.NON_ACTIONABLE,
        }:
            raise ValueError("model dropped a material request clause")

        deterministic_budget = deterministic_budget_constraints(source.source_text)
        if deterministic_budget:
            expected = deterministic_budget[0]["params"]
            if not any(
                constraint.category == "budget_cap"
                and constraint.params.amount == expected["amount"]
                and str(constraint.params.currency or "").upper()
                == str(expected["currency"]).upper()
                and constraint.params.per == expected["per"]
                for constraint in draft.constraints
            ):
                raise ValueError(
                    "model changed or omitted an explicit numeric budget cap"
                )

        source_text = source.source_text.casefold()
        if not any(cue in source_text for cue in _MONETARY_CUES) and any(
            constraint.category == "budget_cap" and constraint.params.amount is not None
            for constraint in draft.constraints
        ):
            raise ValueError("model inferred a numeric budget from non-monetary text")

        if any(cue in source_text for cue in _ALTERNATIVE_REQUEST_CUES) and not any(
            intent.kind is IntentKind.ALTERNATIVES
            and intent.strength is IntentStrength.HARD
            and intent.target is IntentTarget.DELIVERY
            and isinstance(intent.value, AlternativeIntentValue)
            for intent in draft.intents
        ):
            raise ValueError("model omitted an explicit alternative request")


def _enforce_deterministic_intents(
    result: RequestContractNormalizationResult,
    clauses: List[SourceClause],
) -> RequestContractNormalizationResult:
    """Split explicit named must-dos in the deterministic fallback path.

    A valid model result is returned unchanged.  This grammar is used only after
    model/schema/contract failure so the degraded run still gives each listed
    item its own stable ID, candidate match, selection role, and fidelity verdict.
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
                ["research", "admission", "ranking", "composition"],
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
