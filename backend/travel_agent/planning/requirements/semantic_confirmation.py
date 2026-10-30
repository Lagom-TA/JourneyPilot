from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from travel_agent.planning.requirements.confirmation_contracts import (
    AssertionCandidate,
    AssertionDecision,
    AssertionDecisionInput,
    AssertionMeaning,
    ConfirmationChallenge,
    ConfirmationReceipt,
    NON_AUTHORIZING_SOURCE_KINDS,
    RequirementDomain,
    RequirementExecution,
    SourceEvidence,
    SourceKind,
    build_assertion_candidate,
    build_confirmation_challenge,
    build_confirmation_receipt,
)
from travel_agent.planning.requirements.confirmation_sources import (
    confirmation_sources_from_intake,
)
from travel_agent.planning.requirements.constraints.sources import (
    constraint_free_text_sources,
)
from travel_agent.planning.requirements.intent_contracts import (
    IntentItem,
    IntentKind,
    IntentTarget,
    canonical_json_hash,
)
from travel_agent.planning.requirements.request_contracts import RequestContract


SEMANTIC_CONFIRMATION_POLICY_VERSION = "request_contract_confirmation.v1"

_DOMAIN_LABELS = {
    RequirementDomain.PLACE: "地点",
    RequirementDomain.ACTIVITY: "景点与体验",
    RequirementDomain.FOOD: "餐饮",
    RequirementDomain.ACCOMMODATION: "住宿",
    RequirementDomain.TRANSPORT: "交通",
    RequirementDomain.PACE: "节奏",
    RequirementDomain.BUDGET: "预算",
    RequirementDomain.ACCESSIBILITY: "无障碍",
    RequirementDomain.SCHEDULE: "时间安排",
    RequirementDomain.CONSTRAINT: "其他限制",
    RequirementDomain.OUTPUT: "输出要求",
}
_TARGET_DOMAINS = {
    IntentTarget.TRIP: RequirementDomain.ACTIVITY,
    IntentTarget.VISIT: RequirementDomain.ACTIVITY,
    IntentTarget.DINING: RequirementDomain.FOOD,
    IntentTarget.LODGING: RequirementDomain.ACCOMMODATION,
    IntentTarget.LOCAL_TRANSPORT: RequirementDomain.TRANSPORT,
    IntentTarget.LONG_DISTANCE_TRANSPORT: RequirementDomain.TRANSPORT,
    IntentTarget.ITINERARY: RequirementDomain.SCHEDULE,
    IntentTarget.DELIVERY: RequirementDomain.OUTPUT,
}
_CONSTRAINT_DOMAINS = {
    "budget_cap": RequirementDomain.BUDGET,
    "elderly_mobility": RequirementDomain.ACCESSIBILITY,
    "health_condition": RequirementDomain.ACCESSIBILITY,
    "food_allergy": RequirementDomain.FOOD,
    "dietary_restriction": RequirementDomain.FOOD,
    "accommodation_preference": RequirementDomain.ACCOMMODATION,
    "transport_constraint": RequirementDomain.TRANSPORT,
    "pace_preference": RequirementDomain.PACE,
}
_NEGATIVE_CONSTRAINTS = frozenset({"food_allergy", "dietary_restriction"})
_ALL_DECISIONS = (
    AssertionDecision.INCLUDE,
    AssertionDecision.AVOID,
    AssertionDecision.HISTORICAL,
    AssertionDecision.UNKNOWN,
)


@dataclass(frozen=True)
class SemanticChallengeBundle:
    sources: Tuple[SourceEvidence, ...]
    assertions: Tuple[AssertionCandidate, ...]
    challenge: Optional[ConfirmationChallenge]
    issues: Tuple[str, ...]


def candidate_without_research_plan(contract: RequestContract) -> RequestContract:
    from travel_agent.planning.requirements.revision import (
        request_contract_with_research_plan,
    )

    return request_contract_with_research_plan(contract, None)


def _source_kind(value: str) -> SourceKind:
    return {
        "current_query": SourceKind.CURRENT_REQUEST,
        "current_request": SourceKind.CURRENT_REQUEST,
        "plan_gate_amendment": SourceKind.EXPLICIT_SUPPLEMENT,
        "run_supplement": SourceKind.EXPLICIT_SUPPLEMENT,
        "memory_fact": SourceKind.SAVED_PREFERENCE,
        "session_anchor": SourceKind.TRIP_CONTEXT,
    }.get(value, SourceKind.TRIP_CONTEXT)


def _sources(state: Any) -> Tuple[SourceEvidence, ...]:
    rows: List[SourceEvidence] = []
    seen: set[str] = set()
    revision = int(getattr(state, "intent_spec_revision", 0) or 0)
    for item in constraint_free_text_sources(state, []):
        source_id = str(item.get("id") or "")
        text = str(item.get("text") or "")
        if not source_id or not text.strip() or source_id in seen:
            continue
        rows.append(SourceEvidence(
            source_id=source_id,
            kind=_source_kind(str(item.get("source") or "")),
            text=text,
            revision=revision,
        ))
        seen.add(source_id)

    intake_groups: Dict[Tuple[str, int], List[Mapping[str, Any]]] = {}
    for record in getattr(state, "intake_evidence_sources", []) or []:
        if not isinstance(record, Mapping):
            continue
        intake_id = record.get("intake_id")
        intake_revision = record.get("intake_revision")
        if isinstance(intake_id, str) and isinstance(intake_revision, int) and not isinstance(intake_revision, bool):
            intake_groups.setdefault((intake_id, intake_revision), []).append(record)
    for (intake_id, intake_revision), records in intake_groups.items():
        for source in confirmation_sources_from_intake(
            list(records), intake_id=intake_id, intake_revision=intake_revision,
        ):
            if source.source_id not in seen:
                rows.append(source)
                seen.add(source.source_id)
    return tuple(rows)


def _party_applies_to(identity: Mapping[str, Any]) -> Tuple[str, ...]:
    party = identity.get("party") or {}
    if not isinstance(party, Mapping):
        return ("本次旅行全体同行",)
    details = [f"{party.get('adults', 0)} 位成人", f"{party.get('children', 0)} 位儿童"]
    if party.get("elderly_companions"):
        details.append("有长辈同行")
    if party.get("accessibility_required"):
        details.append("需要无障碍安排")
    return (f"全体同行：{'、'.join(details)}",)


def _intent_scope(item: IntentItem) -> str:
    value = item.value.model_dump(mode="json")
    value_type = value.get("value_type")
    if value_type == "count":
        return f"count:{value.get('unit')}"
    if value_type == "cadence":
        return f"cadence:{value.get('frequency')}"
    if value_type in {"time_window", "output_requirement"}:
        return str(value.get("applies_to") or item.target.value)
    return item.target.value


def _intent_evidence_texts(item: IntentItem) -> Tuple[str, ...]:
    value = item.value.model_dump(mode="json")
    value_type = value.get("value_type")
    if value_type == "scalar":
        keys = ("value",)
    elif value_type == "category":
        keys = ("categories",)
    elif value_type == "sequence":
        keys = ("ordered_items",)
    elif value_type == "geographic":
        keys = ("area",)
    elif value_type == "cadence":
        keys = ("time_window", "required_attributes")
    elif value_type == "time_window":
        keys = ("window",)
    elif value_type == "output_requirement":
        keys = ("required_field",)
    elif value_type == "alternative":
        keys = ("distinction",)
    else:
        keys = ()
    found: List[str] = []
    for key in keys:
        raw = value.get(key)
        for text in raw if isinstance(raw, list) else [raw]:
            if isinstance(text, str) and text.strip():
                found.append(text)
    return tuple(found)


def _locate(source: SourceEvidence, quote: str, preferred_start: Optional[int] = None) -> int:
    if preferred_start is not None and source.text[preferred_start:preferred_start + len(quote)] == quote:
        return preferred_start
    return source.text.find(quote)


def _execution_for_intent(item: IntentItem, identity: Mapping[str, Any]) -> RequirementExecution:
    return RequirementExecution(
        requirement_id=item.intent_id,
        requirement_type="intent",
        kind=item.kind.value,
        target=item.target.value,
        polarity="exclude" if item.kind is IntentKind.MUST_EXCLUDE else "include",
        strength=item.strength.value,
        value=item.value.model_dump(mode="json"),
        applies_to=_party_applies_to(identity),
        scope=_intent_scope(item),
        public_summary=item.public_summary,
    )


def _intent_assertion(
    item: IntentItem,
    source_by_id: Mapping[str, SourceEvidence],
    identity: Mapping[str, Any],
) -> Tuple[Optional[AssertionCandidate], Optional[str]]:
    source = source_by_id.get(item.source_ref_id)
    if source is None or source.kind in NON_AUTHORIZING_SOURCE_KINDS:
        return None, "有一条历史偏好需要你在本次请求或补充中重新说明。"
    quote = str(item.source_text or "").strip()
    if not quote or len(quote) > 500:
        return None, f"「{item.public_summary}」的原文无法安全定位，请重新说明。"
    start = _locate(source, quote, item.source_span_start)
    if start < 0:
        return None, f"「{item.public_summary}」与本次原文版本不一致，请重新说明。"
    evidence_texts = _intent_evidence_texts(item)
    if any(text not in quote for text in evidence_texts):
        return None, f"「{item.public_summary}」包含无法在本次原文中定位的内容，请纠正或补充。"
    object_label = evidence_texts[0] if evidence_texts else quote
    if len(object_label) > 200:
        object_label = object_label[:200]
    meaning = (
        AssertionMeaning.EXCLUDE
        if item.kind is IntentKind.MUST_EXCLUDE
        else AssertionMeaning.PREFERENCE
        if item.strength.value == "soft"
        else AssertionMeaning.INCLUDE
    )
    return build_assertion_candidate(
        source=source,
        span_start=start,
        span_end=start + len(quote),
        quote=quote,
        domain=_TARGET_DOMAINS[item.target],
        meaning=meaning,
        allowed_decisions=_ALL_DECISIONS,
        object_label=object_label,
        execution=_execution_for_intent(item, identity),
    ), None


def _constraint_assertion(
    item: Mapping[str, Any],
    source_by_id: Mapping[str, SourceEvidence],
    identity: Mapping[str, Any],
) -> Tuple[Optional[AssertionCandidate], Optional[str]]:
    summary = str(item.get("public_summary") or item.get("value") or "约束")
    refs = [ref for ref in item.get("source_refs") or [] if isinstance(ref, Mapping)]
    source = next(
        (
            source_by_id[str(ref.get("origin_ref") or "")]
            for ref in refs
            if str(ref.get("origin_ref") or "") in source_by_id
            and source_by_id[str(ref.get("origin_ref") or "")].kind not in NON_AUTHORIZING_SOURCE_KINDS
        ),
        None,
    )
    if source is None:
        return None, f"「{summary}」来自历史或无法核实的来源，请在本次补充中重新明确。"
    value = str(item.get("value") or "").strip()
    quote = value if value and value in source.text else source.text
    start = _locate(source, quote)
    if not quote or len(quote) > 500 or start < 0:
        return None, f"「{summary}」的来源范围无法安全核对，请重新说明。"
    category = str(item.get("category") or "other")
    object_label = value if value and value in quote and len(value) <= 200 else quote[:200]
    strength = str(item.get("type") or "informational")
    if strength not in {"hard", "soft", "informational"}:
        strength = "informational"
    negative = category in _NEGATIVE_CONSTRAINTS
    execution = RequirementExecution(
        requirement_id=str(item.get("constraint_id") or ""),
        requirement_type="constraint",
        kind=category,
        target=category,
        polarity="exclude" if negative else "neutral",
        strength=strength,
        value={"value": quote, "params": item.get("params") or {}},
        applies_to=_party_applies_to(identity),
        scope=(
            f"budget:{(item.get('params') or {}).get('per')}"
            if category == "budget_cap" and isinstance(item.get("params"), Mapping) and (item.get("params") or {}).get("per")
            else category
        ),
        public_summary=summary,
    )
    return build_assertion_candidate(
        source=source,
        span_start=start,
        span_end=start + len(quote),
        quote=quote,
        domain=_CONSTRAINT_DOMAINS.get(category, RequirementDomain.CONSTRAINT),
        meaning=AssertionMeaning.EXCLUDE if negative else AssertionMeaning.CONSTRAINT,
        allowed_decisions=_ALL_DECISIONS,
        object_label=object_label,
        execution=execution,
    ), None


def build_semantic_challenge(state: Any, contract: RequestContract) -> SemanticChallengeBundle:
    sources = _sources(state)
    source_by_id = {source.source_id: source for source in sources}
    assertions: List[AssertionCandidate] = []
    issues: List[str] = []
    for item in contract.intent_spec.active_items:
        assertion, issue = _intent_assertion(item, source_by_id, state.controlled_trip_identity)
        if assertion is not None:
            assertions.append(assertion)
        if issue:
            issues.append(issue)
    seen_constraints: set[str] = set()
    for item in contract.constraint_pack.get("constraints") or []:
        if not isinstance(item, Mapping) or item.get("status") not in (None, "active"):
            continue
        if item.get("visibility") == "internal_only":
            continue
        refs = [ref for ref in item.get("source_refs") or [] if isinstance(ref, Mapping)]
        if not any(
            str(ref.get("source") or "") in {"current_query", "plan_gate_amendment", "run_supplement"}
            for ref in refs
        ):
            continue
        constraint_id = str(item.get("constraint_id") or "")
        if not constraint_id or constraint_id in seen_constraints:
            continue
        seen_constraints.add(constraint_id)
        assertion, issue = _constraint_assertion(item, source_by_id, state.controlled_trip_identity)
        if assertion is not None:
            assertions.append(assertion)
        if issue:
            issues.append(issue)
    if not assertions and not issues:
        issues.append("尚未整理出可核对的本次需求，请补充你的要求。")
    challenge = None
    if assertions and not issues:
        challenge = build_confirmation_challenge(
            run_id=state.run_id,
            session_id=state.session_id or state.run_id,
            revision=contract.intent_spec.revision,
            identity_hash=canonical_json_hash(state.controlled_trip_identity),
            policy_version=SEMANTIC_CONFIRMATION_POLICY_VERSION,
            candidate_contract_hash=contract.content_hash,
            sources=sources,
            assertions=assertions,
        )
    return SemanticChallengeBundle(
        sources=tuple(sources),
        assertions=tuple(assertions),
        challenge=challenge,
        issues=tuple(dict.fromkeys(issues)),
    )


def public_semantic_assertions(bundle: SemanticChallengeBundle) -> List[Dict[str, Any]]:
    source_by_id = {source.source_id: source for source in bundle.sources}
    rows: List[Dict[str, Any]] = []
    for assertion in bundle.assertions:
        source = source_by_id[assertion.source_id]
        rows.append({
            "assertion_id": assertion.assertion_id,
            "source_kind": source.kind.value,
            "context": source.text,
            "question_context": source.context,
            "quote": assertion.quote,
            "object_label": assertion.object_label,
            "domain_label": _DOMAIN_LABELS[assertion.domain],
            "allowed_decisions": [decision.value for decision in assertion.allowed_decisions],
            "execution": assertion.execution.model_dump(mode="json") if assertion.execution else None,
        })
    return rows


def receipt_from_decision(
    state: Any,
    bundle: SemanticChallengeBundle,
    decision: Mapping[str, Any],
) -> ConfirmationReceipt:
    if bundle.challenge is None:
        raise ValueError("semantic challenge is not ready")
    confirmation = decision.get("semantic_confirmation")
    if not isinstance(confirmation, Mapping):
        raise ValueError("semantic confirmation is required")
    if confirmation.get("revision") != bundle.challenge.revision:
        raise ValueError("semantic confirmation revision is stale")
    raw_decisions = confirmation.get("decisions")
    if not isinstance(raw_decisions, Sequence) or isinstance(raw_decisions, (str, bytes)):
        raise ValueError("semantic decisions must be a list")
    decisions = [AssertionDecisionInput.model_validate(item) for item in raw_decisions]
    return build_confirmation_receipt(
        challenge=bundle.challenge,
        sources=bundle.sources,
        assertions=bundle.assertions,
        decisions=decisions,
        submitted_token=str(confirmation.get("challenge_id") or ""),
        run_id=state.run_id,
        session_id=state.session_id or state.run_id,
        identity_hash=canonical_json_hash(state.controlled_trip_identity),
        policy_version=SEMANTIC_CONFIRMATION_POLICY_VERSION,
    )


def receipt_covers_every_requirement(
    receipt: ConfirmationReceipt,
    bundle: SemanticChallengeBundle,
) -> bool:
    included = set(receipt.included_assertion_ids)
    return (
        not receipt.incomplete
        and len(included) == len(bundle.assertions)
        and all(assertion.assertion_id in included for assertion in bundle.assertions)
        and all(assertion.execution is not None for assertion in bundle.assertions)
    )
