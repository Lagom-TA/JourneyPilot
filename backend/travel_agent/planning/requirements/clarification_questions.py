from __future__ import annotations

from typing import Any, Optional, Tuple

from travel_agent.planning.requirements.confirmation_contracts import AssertionMeaning
from travel_agent.planning.requirements.request_contracts import RequestContract
from travel_agent.planning.requirements.semantic_confirmation import build_semantic_challenge


def _exclusion_keys(assertion) -> Tuple[str, ...]:
    import re

    from travel_agent.planning.research.research_plan_validation import (
        _restriction_fragments,
    )

    fragments = set()
    for piece in re.split(r"[；;：:]", assertion.normalized_object):
        if piece in {"是", "是的", "对", "好", "好的", "确认"}:
            continue
        fragments.update(_restriction_fragments(piece))
    ordered = sorted(fragments, key=lambda value: (len(value), value))
    return (ordered[0] if ordered else assertion.normalized_object,)


def next_exclusion_key(state: Any, contract: RequestContract) -> Optional[str]:
    bundle = build_semantic_challenge(state, contract)
    if bundle.issues or any(assertion.execution is None for assertion in bundle.assertions):
        return None
    answered = set(getattr(state, "clarified_exclusion_keys", []) or [])
    for assertion in bundle.assertions:
        if assertion.meaning is AssertionMeaning.EXCLUDE and assertion.execution is not None:
            for key in _exclusion_keys(assertion):
                if key not in answered:
                    return key
    return None


def necessary_requirement_questions(state: Any, contract: RequestContract) -> Tuple[str, ...]:
    bundle = build_semantic_challenge(state, contract)
    if bundle.issues:
        return (bundle.issues[0],)
    for assertion in bundle.assertions:
        if assertion.execution is None:
            return ("有一项要求的执行含义还不完整，请补充说明。",)
    exclusion_key = next_exclusion_key(state, contract)
    if exclusion_key is not None:
        execution = next(
            assertion.execution
            for assertion in bundle.assertions
            if assertion.execution is not None
            and exclusion_key in _exclusion_keys(assertion)
        )
        return (f"请确认：「{execution.public_summary}」是要避开或排除，而不是要研究或安排它吗？",)
    for assertion in bundle.assertions:
        execution = assertion.execution
        if execution.kind == "budget_cap":
            params = execution.value.get("params") or {}
            if not isinstance(params, dict) or any(params.get(key) in (None, "") for key in ("amount", "currency", "per")):
                return ("请说明预算金额、币种，以及按每晚、每天还是全程计算。",)
    return ()
