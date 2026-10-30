"""执行字段进入确认摘要的离线契约测试（无网络、无数据库、无模型调用）。"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from typing import Dict
from typing import Optional

import pytest
from pydantic import ValidationError

from travel_agent.planning.requirements.confirmation_contracts import (
    CONFIRMATION_CONTRACT_VERSION,
    MAX_EXECUTION_APPLIES_TO,
    MAX_EXECUTION_APPLIES_TO_ITEM_CHARS,
    MAX_EXECUTION_PUBLIC_SUMMARY_CHARS,
    MAX_EXECUTION_VALUE_CHARS,
    MAX_EXECUTION_VALUE_DEPTH,
    MAX_EXECUTION_VALUE_STRING_CHARS,
    AssertionCandidate,
    AssertionDecision,
    AssertionDecisionInput,
    AssertionMeaning,
    ConfirmationChallenge,
    ConfirmationReceipt,
    RequirementDomain,
    RequirementExecution,
    SourceEvidence,
    SourceKind,
    build_assertion_candidate,
    build_confirmation_challenge,
    build_confirmation_receipt,
)


IDENTITY_HASH = hashlib.sha256(b"identity:execution").hexdigest()
POLICY_VERSION = "confirmation-policy.execution.v1"
CANDIDATE_CONTRACT_HASH = hashlib.sha256(
    b"candidate-contract:execution"
).hexdigest()
ALL_DECISIONS = (
    AssertionDecision.INCLUDE,
    AssertionDecision.AVOID,
    AssertionDecision.HISTORICAL,
    AssertionDecision.UNKNOWN,
)
SOURCE_TEXT = "想去杭州，至少两天安排烤肉，预算每人每晚八百元。"


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _source() -> SourceEvidence:
    return SourceEvidence(
        source_id="source_execution",
        kind=SourceKind.CURRENT_REQUEST,
        text=SOURCE_TEXT,
        revision=0,
    )


def _value(**overrides: Any) -> Dict[str, Any]:
    value: Dict[str, Any] = {
        "value_type": "count",
        "operator": "at_least",
        "count": 2,
        "unit": "day",
        "budget": {
            "amount": 800,
            "currency": "CNY",
            "basis": "per_person_per_night",
        },
    }
    value.update(overrides)
    return value


def _value_with_budget_basis(basis: str) -> Dict[str, Any]:
    value = _value()
    value["budget"] = {**value["budget"], "basis": basis}
    return value


def _execution(**overrides: Any) -> RequirementExecution:
    data: Dict[str, Any] = {
        "requirement_id": "req_food_1",
        "requirement_type": "intent",
        "kind": "must_include",
        "target": "dining",
        "polarity": "include",
        "strength": "hard",
        "value": _value(),
        "applies_to": ("trip",),
        "scope": "whole_trip",
        "public_summary": "至少两天安排烤肉，预算每人每晚八百元",
    }
    data.update(overrides)
    return RequirementExecution(**data)


def _candidate(
    execution: Optional[RequirementExecution] = None,
    *,
    source: Optional[SourceEvidence] = None,
) -> AssertionCandidate:
    source = _source() if source is None else source
    quote = "烤肉"
    start = source.text.index(quote)
    return build_assertion_candidate(
        source=source,
        span_start=start,
        span_end=start + len(quote),
        quote=quote,
        domain=RequirementDomain.FOOD,
        meaning=AssertionMeaning.INCLUDE,
        allowed_decisions=ALL_DECISIONS,
        object_label=quote,
        execution=execution,
    )


def _challenge(
    candidate: AssertionCandidate,
    *,
    source: Optional[SourceEvidence] = None,
) -> ConfirmationChallenge:
    return build_confirmation_challenge(
        run_id="run_execution",
        session_id="session_execution",
        revision=1,
        identity_hash=IDENTITY_HASH,
        policy_version=POLICY_VERSION,
        candidate_contract_hash=CANDIDATE_CONTRACT_HASH,
        sources=[_source() if source is None else source],
        assertions=[candidate],
    )


def _receipt(
    candidate: AssertionCandidate,
    *,
    source: Optional[SourceEvidence] = None,
) -> ConfirmationReceipt:
    source = _source() if source is None else source
    challenge = _challenge(candidate, source=source)
    return build_confirmation_receipt(
        challenge=challenge,
        sources=[source],
        assertions=[candidate],
        decisions=[
            AssertionDecisionInput(
                assertion_id=candidate.assertion_id,
                decision=AssertionDecision.INCLUDE,
            )
        ],
        submitted_token=challenge.token,
        run_id=challenge.run_id,
        session_id=challenge.session_id,
        identity_hash=challenge.identity_hash,
        policy_version=challenge.policy_version,
    )


def _nested_value(depth: int) -> Dict[str, Any]:
    value: object = 0
    for _ in range(depth):
        value = {"n": value}
    return value  # type: ignore[return-value]


def _oversized_value() -> Dict[str, Any]:
    return {f"k{index}": "x" * 1_900 for index in range(5)}


def test_execution_content_changes_assertion_identity_and_hash() -> None:
    source = _source()
    baseline = _candidate(_execution(), source=source)
    baseline_challenge = _challenge(baseline, source=source)

    variants = {
        "quantity": _execution(value=_value(count=3)),
        "budget_basis": _execution(
            value=_value_with_budget_basis("per_group")
        ),
        "applies_to": _execution(applies_to=("trip", "day_1")),
        "scope": _execution(scope="day_1"),
        "strength": _execution(strength="soft"),
        "polarity": _execution(polarity="exclude"),
    }
    seen_ids = {baseline.assertion_id}
    for label, execution in variants.items():
        candidate = _candidate(execution, source=source)
        assert candidate.execution == execution, label
        assert candidate.assertion_id != baseline.assertion_id, label
        assert candidate.assertion_hash != baseline.assertion_hash, label
        assert candidate.assertion_id not in seen_ids, label
        seen_ids.add(candidate.assertion_id)
        assert (
            _challenge(candidate, source=source).token
            != baseline_challenge.token
        ), label

    assert _candidate(None, source=source).assertion_id != baseline.assertion_id


def test_legacy_candidate_and_receipt_without_execution_keep_old_hash() -> None:
    source = _source()
    candidate = _candidate(None, source=source)
    assert candidate.execution is None

    legacy_core = {
        "schema_version": CONFIRMATION_CONTRACT_VERSION,
        "source_id": candidate.source_id,
        "source_hash": candidate.source_hash,
        "span_start": candidate.span_start,
        "span_end": candidate.span_end,
        "quote": candidate.quote,
        "domain": candidate.domain.value,
        "meaning": candidate.meaning.value,
        "allowed_decisions": [
            item.value for item in candidate.allowed_decisions
        ],
        "object_label": candidate.object_label,
        "normalized_object": candidate.normalized_object,
    }
    legacy_id = f"assertion_{_digest(legacy_core)[:24]}"
    assert candidate.assertion_id == legacy_id
    assert candidate.assertion_hash == _digest(
        {**legacy_core, "assertion_id": legacy_id}
    )

    receipt = _receipt(candidate, source=source)
    assert receipt.decisions[0].execution is None
    assert ConfirmationReceipt.model_validate(receipt.model_dump()) == receipt


def test_receipt_tampering_with_any_execution_field_is_rejected() -> None:
    source = _source()
    execution = _execution()
    candidate = _candidate(execution, source=source)
    receipt = _receipt(candidate, source=source)

    assert receipt.decisions[0].execution == execution
    data = receipt.model_dump()
    assert (
        data["decisions"][0]["execution"]["value"]["budget"]["basis"]
        == "per_person_per_night"
    )
    assert ConfirmationReceipt.model_validate(data) == receipt
    assert receipt.model_copy() == receipt

    tampered_fields = [
        ("requirement_id", "req_other"),
        ("requirement_type", "constraint"),
        ("kind", "must_exclude"),
        ("target", "lodging"),
        ("polarity", "exclude"),
        ("strength", "soft"),
        ("value", _value_with_budget_basis("per_group")),
        ("applies_to", ("day_1",)),
        ("scope", "day_1"),
        ("public_summary", "改动后的公开摘要"),
    ]
    for field, replacement in tampered_fields:
        data = receipt.model_dump()
        data["decisions"][0]["execution"][field] = replacement
        data["receipt_hash"] = ""
        with pytest.raises(ValidationError, match="assertion_hash"):
            ConfirmationReceipt.model_validate(data)

    data = receipt.model_dump()
    data["decisions"][0]["execution"]["value"] = {"count": float("nan")}
    data["receipt_hash"] = ""
    with pytest.raises(ValidationError):
        ConfirmationReceipt.model_validate(data)


@pytest.mark.parametrize(
    "value",
    [
        {"count": float("nan")},
        {"count": float("inf")},
        {"count": float("-inf")},
        {"items": {1, 2}},
        {"items": (1, 2)},
        {"items": b"bytes"},
        {"text": "x" * (MAX_EXECUTION_VALUE_STRING_CHARS + 1)},
        _oversized_value(),
        _nested_value(MAX_EXECUTION_VALUE_DEPTH + 1),
    ],
)
def test_requirement_execution_rejects_non_json_non_finite_and_unbounded_value(
    value: Dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        _execution(value=value)


def test_requirement_execution_accepts_value_at_depth_limit() -> None:
    value = _nested_value(MAX_EXECUTION_VALUE_DEPTH)
    assert _execution(value=value).value == value


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("requirement_id", ""),
        ("requirement_type", "preference"),
        ("kind", ""),
        ("target", "x" * 201),
        ("polarity", "avoid"),
        ("strength", "required"),
        ("applies_to", ()),
        ("applies_to", ("",)),
        ("applies_to", ("x" * (MAX_EXECUTION_APPLIES_TO_ITEM_CHARS + 1),)),
        (
            "applies_to",
            tuple(f"scope_{index}" for index in range(MAX_EXECUTION_APPLIES_TO + 1)),
        ),
        ("scope", ""),
        ("public_summary", "x" * (MAX_EXECUTION_PUBLIC_SUMMARY_CHARS + 1)),
        ("value", {"text": "x" * (MAX_EXECUTION_VALUE_CHARS + 1)}),
    ],
)
def test_requirement_execution_rejects_invalid_fields(
    field: str,
    value: object,
) -> None:
    data: Dict[str, Any] = {
        "requirement_id": "req_food_1",
        "requirement_type": "intent",
        "kind": "must_include",
        "target": "dining",
        "polarity": "include",
        "strength": "hard",
        "value": _value(),
        "applies_to": ("trip",),
        "scope": "whole_trip",
        "public_summary": "至少两天安排烤肉",
    }
    data[field] = value
    with pytest.raises(ValidationError):
        RequirementExecution(**data)
