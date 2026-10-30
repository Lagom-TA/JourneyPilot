"""语义需求确认原型的离线契约测试（无网络、无数据库、无模型调用）。"""

from __future__ import annotations

import hashlib
from typing import Optional

import pytest
from pydantic import ValidationError

from travel_agent.planning.requirements.confirmation_contracts import (
    MAX_CONTEXT_CHARS,
    AssertionCandidate,
    AssertionDecision,
    AssertionDecisionInput,
    AssertionMeaning,
    ConfirmationChallenge,
    ConfirmationContractError,
    ConfirmationReceipt,
    ConfirmationRejected,
    RequirementDomain,
    SourceEvidence,
    SourceKind,
    build_assertion_candidate,
    build_confirmation_challenge,
    build_confirmation_receipt,
)


IDENTITY_HASH = hashlib.sha256(b"identity:test").hexdigest()
POLICY_VERSION = "confirmation-policy.v1"
CANDIDATE_CONTRACT_HASH = hashlib.sha256(b"candidate-contract:test").hexdigest()
ALL_DECISIONS = (
    AssertionDecision.INCLUDE,
    AssertionDecision.AVOID,
    AssertionDecision.HISTORICAL,
    AssertionDecision.UNKNOWN,
)


def _source(
    text: str = "我想去杭州，吃烤肉，避开西湖。",
    *,
    kind: SourceKind = SourceKind.CURRENT_REQUEST,
    source_id: str = "source_current",
    revision: int = 0,
    context: Optional[str] = None,
) -> SourceEvidence:
    return SourceEvidence(
        source_id=source_id,
        kind=kind,
        text=text,
        revision=revision,
        context=context,
    )


def _candidate(
    source: SourceEvidence,
    quote: str,
    *,
    object_label: Optional[str] = None,
    domain: RequirementDomain = RequirementDomain.FOOD,
    meaning: AssertionMeaning = AssertionMeaning.INCLUDE,
    allowed_decisions: tuple[AssertionDecision, ...] = ALL_DECISIONS,
    start: Optional[int] = None,
):
    if start is None:
        start = source.text.index(quote)
    return build_assertion_candidate(
        source=source,
        span_start=start,
        span_end=start + len(quote),
        quote=quote,
        domain=domain,
        meaning=meaning,
        allowed_decisions=allowed_decisions,
        object_label=object_label or quote,
    )


def _challenge(
    sources,
    assertions,
    *,
    revision: int = 1,
    run_id: str = "run_1",
    session_id: str = "session_1",
    candidate_contract_hash: str = CANDIDATE_CONTRACT_HASH,
    previous: Optional[ConfirmationChallenge] = None,
) -> ConfirmationChallenge:
    return build_confirmation_challenge(
        run_id=run_id,
        session_id=session_id,
        revision=revision,
        identity_hash=IDENTITY_HASH,
        policy_version=POLICY_VERSION,
        candidate_contract_hash=candidate_contract_hash,
        sources=tuple(sources),
        assertions=tuple(assertions),
        previous=previous,
    )


def _receipt(
    challenge: ConfirmationChallenge,
    sources,
    assertions,
    decisions,
    *,
    token: Optional[str] = None,
    run_id: Optional[str] = None,
    session_id: Optional[str] = None,
    identity_hash: Optional[str] = None,
    policy_version: Optional[str] = None,
):
    return build_confirmation_receipt(
        challenge=challenge,
        sources=tuple(sources),
        assertions=tuple(assertions),
        decisions=tuple(decisions),
        submitted_token=challenge.token if token is None else token,
        run_id=challenge.run_id if run_id is None else run_id,
        session_id=challenge.session_id if session_id is None else session_id,
        identity_hash=(
            challenge.identity_hash if identity_hash is None else identity_hash
        ),
        policy_version=(
            challenge.policy_version
            if policy_version is None
            else policy_version
        ),
    )


def test_source_evidence_hash_covers_full_text_and_is_deterministic():
    text = "第一行：想吃烤肉。\n第二行：避开西湖。\n" + "补充" * 200
    source = _source(text)
    same = _source(text)
    changed = _source(text + "！")

    assert source.text == text
    assert source.source_hash == same.source_hash
    assert source.source_hash != changed.source_hash
    assert len(source.source_hash) == 64

    # 修订号和来源类别同样是来源身份的一部分。
    next_revision = _source(text, revision=1)
    other_kind = _source(text, kind=SourceKind.EXPLICIT_SUPPLEMENT)
    assert next_revision.source_hash != source.source_hash
    assert other_kind.source_hash != source.source_hash

    # 手填错误摘要不能通过。
    with pytest.raises(ValidationError):
        SourceEvidence(
            source_id=source.source_id,
            kind=source.kind,
            text=source.text,
            revision=source.revision,
            source_hash="0" * 64,
        )


def test_source_context_is_bounded_and_changes_hash():
    context = "问题：你想去哪里？"
    source = _source("想去杭州。", context=context)
    same = _source("想去杭州。", context=context)
    changed = _source("想去杭州。", context=context + "（已替换）")
    assert source.context == context
    assert source.source_hash == same.source_hash
    assert source.source_hash != changed.source_hash

    with pytest.raises(ValidationError):
        _source("想去杭州。", context="x" * (MAX_CONTEXT_CHARS + 1))


def test_context_change_invalidates_challenge_token_and_receipt():
    source_old = _source("想去杭州。", context="问题：你想去哪里？")
    source_new = _source("想去杭州。", context="问题：你想去哪里？[已替换]")
    candidate_old = _candidate(source_old, "杭州", object_label="杭州")
    candidate_new = _candidate(source_new, "杭州", object_label="杭州")
    challenge_old = _challenge([source_old], [candidate_old])
    challenge_new = _challenge([source_new], [candidate_new])
    assert challenge_old.token != challenge_new.token

    decision_old = AssertionDecisionInput(
        assertion_id=candidate_old.assertion_id,
        decision=AssertionDecision.INCLUDE,
    )
    receipt_old = _receipt(
        challenge_old,
        [source_old],
        [candidate_old],
        [decision_old],
    )
    receipt_new = _receipt(
        challenge_new,
        [source_new],
        [candidate_new],
        [
            AssertionDecisionInput(
                assertion_id=candidate_new.assertion_id,
                decision=AssertionDecision.INCLUDE,
            )
        ],
    )
    assert receipt_old.sources[0].context == source_old.context
    assert receipt_new.sources[0].context == source_new.context
    assert receipt_old.receipt_hash != receipt_new.receipt_hash

    with pytest.raises(ConfirmationRejected, match="stale"):
        _receipt(
            challenge_new,
            [source_old],
            [candidate_old],
            [decision_old],
            token=challenge_old.token,
        )
    with pytest.raises(ConfirmationRejected, match="digests"):
        _receipt(
            challenge_new,
            [source_old],
            [candidate_old],
            [decision_old],
        )

    with pytest.raises(ValidationError):
        source_old.model_copy(update={"context": source_new.context})

    data = receipt_old.model_dump()
    data["sources"][0]["context"] = source_new.context
    with pytest.raises(ValidationError):
        ConfirmationReceipt.model_validate(data)


def test_context_is_not_valid_evidence_for_quote_or_object():
    source = _source("杭州", context="东京迪士尼")
    valid = _candidate(source, "杭州", object_label="杭州")
    assert valid.quote == source.text

    with pytest.raises(ConfirmationContractError, match="object label"):
        _candidate(source, "杭州", object_label="东京迪士尼")

    with pytest.raises(ConfirmationContractError, match="quote"):
        build_assertion_candidate(
            source=source,
            span_start=0,
            span_end=2,
            quote="东京",
            domain=RequirementDomain.PLACE,
            meaning=AssertionMeaning.INCLUDE,
            allowed_decisions=ALL_DECISIONS,
            object_label="东京",
        )

    with pytest.raises(ConfirmationContractError, match="outside"):
        build_assertion_candidate(
            source=source,
            span_start=0,
            span_end=5,
            quote="东京迪士尼",
            domain=RequirementDomain.PLACE,
            meaning=AssertionMeaning.INCLUDE,
            allowed_decisions=ALL_DECISIONS,
            object_label="东京迪士尼",
        )


@pytest.mark.parametrize(
    "decision",
    [AssertionDecision.INCLUDE, AssertionDecision.AVOID],
)
def test_explicit_selection_requires_independent_text_evidence(
    decision: AssertionDecision,
) -> None:
    # 原文只说杭州，选项去东京；问题 context 里出现东京也不算独立证据。
    original = _source(
        "我这次只去杭州。",
        source_id="source_request",
        context="问题里也会出现东京。",
    )
    selection = _source(
        "选项：去东京",
        kind=SourceKind.EXPLICIT_SELECTION,
        source_id="source_selection",
        context="问题：要不要去东京？",
    )
    candidate = _candidate(selection, "东京", object_label="东京")
    challenge = _challenge([original, selection], [candidate])

    with pytest.raises(ConfirmationRejected, match="independent text evidence"):
        _receipt(
            challenge,
            [original, selection],
            [candidate],
            [
                AssertionDecisionInput(
                    assertion_id=candidate.assertion_id,
                    decision=decision,
                )
            ],
        )


@pytest.mark.parametrize(
    "decision",
    [AssertionDecision.HISTORICAL, AssertionDecision.AVOID],
)
def test_selection_historical_or_avoid_allowed_when_original_mentions_object(
    decision: AssertionDecision,
) -> None:
    original = _source("我提到杭州。", source_id="source_request")
    selection = _source(
        "选项：杭州",
        kind=SourceKind.EXPLICIT_SELECTION,
        source_id="source_selection",
    )
    candidate = _candidate(selection, "杭州", object_label="杭州")
    challenge = _challenge([original, selection], [candidate])
    receipt = _receipt(
        challenge,
        [original, selection],
        [candidate],
        [
            AssertionDecisionInput(
                assertion_id=candidate.assertion_id,
                decision=decision,
            )
        ],
    )

    if decision is AssertionDecision.AVOID:
        assert receipt.avoided_assertion_ids == (candidate.assertion_id,)
    else:
        assert receipt.historical_assertion_ids == (candidate.assertion_id,)
    assert not receipt.incomplete


@pytest.mark.parametrize(
    "evidence_kind",
    [
        SourceKind.CURRENT_REQUEST,
        SourceKind.EXPLICIT_SUPPLEMENT,
        SourceKind.STRUCTURED_FORM,
    ],
)
def test_selection_include_allowed_with_independent_text_evidence(
    evidence_kind: SourceKind,
) -> None:
    evidence = _source(
        "用户原文提到杭州。",
        kind=evidence_kind,
        source_id=f"source_{evidence_kind.value}",
    )
    selection = _source(
        "选项：杭州",
        kind=SourceKind.EXPLICIT_SELECTION,
        source_id="source_selection",
    )
    candidate = _candidate(selection, "杭州", object_label="杭州")
    challenge = _challenge([evidence, selection], [candidate])
    receipt = _receipt(
        challenge,
        [evidence, selection],
        [candidate],
        [
            AssertionDecisionInput(
                assertion_id=candidate.assertion_id,
                decision=AssertionDecision.INCLUDE,
            )
        ],
    )
    assert receipt.included_assertion_ids == (candidate.assertion_id,)
    assert not receipt.incomplete


@pytest.mark.parametrize(
    "decision",
    [AssertionDecision.INCLUDE, AssertionDecision.AVOID],
)
def test_receipt_rejects_selection_without_independent_evidence_on_deserialization(
    decision: AssertionDecision,
) -> None:
    original = _source("我这次只去杭州。", source_id="source_request")
    selection = _source(
        "选项：去东京",
        kind=SourceKind.EXPLICIT_SELECTION,
        source_id="source_selection",
        context="问题：要不要去东京？",
    )
    candidate = _candidate(selection, "东京", object_label="东京")
    challenge = _challenge([original, selection], [candidate])
    receipt = _receipt(
        challenge,
        [original, selection],
        [candidate],
        [
            AssertionDecisionInput(
                assertion_id=candidate.assertion_id,
                decision=AssertionDecision.HISTORICAL,
            )
        ],
    )

    data = receipt.model_dump()
    data["decisions"][0]["decision"] = decision.value
    data["historical_assertion_ids"] = ()
    data["included_assertion_ids"] = (
        (candidate.assertion_id,)
        if decision is AssertionDecision.INCLUDE
        else ()
    )
    data["avoided_assertion_ids"] = (
        (candidate.assertion_id,)
        if decision is AssertionDecision.AVOID
        else ()
    )
    data["receipt_hash"] = ""
    with pytest.raises(ValidationError, match="independent text evidence"):
        ConfirmationReceipt.model_validate(data)


def test_allowlist_is_bound_into_assertion_and_challenge():
    source = _source("想去杭州。")
    narrow = _candidate(
        source,
        "杭州",
        object_label="杭州",
        allowed_decisions=(
            AssertionDecision.AVOID,
            AssertionDecision.HISTORICAL,
        ),
    )
    wide = _candidate(
        source,
        "杭州",
        object_label="杭州",
        allowed_decisions=(
            AssertionDecision.INCLUDE,
            AssertionDecision.AVOID,
            AssertionDecision.HISTORICAL,
        ),
    )
    assert narrow.assertion_id != wide.assertion_id
    assert narrow.assertion_hash != wide.assertion_hash
    assert (
        _challenge([source], [narrow]).token
        != _challenge([source], [wide]).token
    )

    data = narrow.model_dump()
    data["allowed_decisions"] = [
        AssertionDecision.INCLUDE,
        AssertionDecision.AVOID,
        AssertionDecision.HISTORICAL,
    ]
    with pytest.raises(ValidationError, match="assertion"):
        AssertionCandidate.model_validate(data)


def test_candidate_contract_hash_changes_challenge_and_receipt():
    source = _source("想去杭州。")
    candidate = _candidate(source, "杭州", object_label="杭州")
    other_contract_hash = hashlib.sha256(
        b"candidate-contract:other"
    ).hexdigest()
    challenge = _challenge([source], [candidate])
    updated = _challenge(
        [source],
        [candidate],
        candidate_contract_hash=other_contract_hash,
    )
    assert challenge.candidate_contract_hash == CANDIDATE_CONTRACT_HASH
    assert updated.candidate_contract_hash == other_contract_hash
    assert challenge.token != updated.token

    decision = AssertionDecisionInput(
        assertion_id=candidate.assertion_id,
        decision=AssertionDecision.INCLUDE,
    )
    receipt = _receipt(challenge, [source], [candidate], [decision])
    updated_receipt = _receipt(updated, [source], [candidate], [decision])
    assert receipt.candidate_contract_hash == CANDIDATE_CONTRACT_HASH
    assert updated_receipt.candidate_contract_hash == other_contract_hash
    assert receipt.receipt_hash != updated_receipt.receipt_hash

    with pytest.raises(ConfirmationRejected, match="stale"):
        _receipt(
            updated,
            [source],
            [candidate],
            [decision],
            token=challenge.token,
        )

    data = receipt.model_dump()
    data["candidate_contract_hash"] = other_contract_hash
    data["receipt_hash"] = ""
    with pytest.raises(ValidationError, match="challenge_token"):
        ConfirmationReceipt.model_validate(data)

    with pytest.raises(ValidationError):
        _challenge(
            [source],
            [candidate],
            candidate_contract_hash="not-a-64-hex-digest",
        )


def test_old_challenge_and_receipt_without_contract_hash_are_rejected():
    source = _source("想去杭州。")
    candidate = _candidate(source, "杭州", object_label="杭州")
    challenge = _challenge([source], [candidate])
    receipt = _receipt(
        challenge,
        [source],
        [candidate],
        [
            AssertionDecisionInput(
                assertion_id=candidate.assertion_id,
                decision=AssertionDecision.INCLUDE,
            )
        ],
    )

    challenge_data = challenge.model_dump()
    challenge_data.pop("candidate_contract_hash")
    challenge_data.pop("token", None)
    with pytest.raises(ValidationError):
        ConfirmationChallenge.model_validate(challenge_data)

    receipt_data = receipt.model_dump()
    receipt_data.pop("candidate_contract_hash")
    receipt_data.pop("receipt_hash", None)
    with pytest.raises(ValidationError):
        ConfirmationReceipt.model_validate(receipt_data)


@pytest.mark.parametrize(
    "allowed_decisions",
    [
        (),
        (AssertionDecision.INCLUDE, AssertionDecision.INCLUDE),
        ("unknown_decision",),
    ],
)
def test_allowlist_rejects_empty_duplicate_and_unknown(
    allowed_decisions,
) -> None:
    source = _source("想去杭州。")
    with pytest.raises(ValidationError):
        _candidate(
            source,
            "杭州",
            object_label="杭州",
            allowed_decisions=allowed_decisions,
        )


def test_allowlist_rejects_include_when_not_allowed():
    source = _source("想去杭州。")
    candidate = _candidate(
        source,
        "杭州",
        object_label="杭州",
        allowed_decisions=(
            AssertionDecision.AVOID,
            AssertionDecision.HISTORICAL,
        ),
    )
    challenge = _challenge([source], [candidate])
    with pytest.raises(ConfirmationRejected, match="not allowed"):
        _receipt(
            challenge,
            [source],
            [candidate],
            [
                AssertionDecisionInput(
                    assertion_id=candidate.assertion_id,
                    decision=AssertionDecision.INCLUDE,
                )
            ],
        )


@pytest.mark.parametrize(
    "decision",
    [
        AssertionDecision.INCLUDE,
        AssertionDecision.AVOID,
        AssertionDecision.HISTORICAL,
    ],
)
def test_allowlist_allows_each_listed_decision(
    decision: AssertionDecision,
) -> None:
    source = _source("想去杭州。")
    candidate = _candidate(
        source,
        "杭州",
        object_label="杭州",
        allowed_decisions=(
            AssertionDecision.INCLUDE,
            AssertionDecision.AVOID,
            AssertionDecision.HISTORICAL,
        ),
    )
    challenge = _challenge([source], [candidate])
    receipt = _receipt(
        challenge,
        [source],
        [candidate],
        [
            AssertionDecisionInput(
                assertion_id=candidate.assertion_id,
                decision=decision,
            )
        ],
    )

    if decision is AssertionDecision.INCLUDE:
        assert receipt.included_assertion_ids == (candidate.assertion_id,)
    elif decision is AssertionDecision.AVOID:
        assert receipt.avoided_assertion_ids == (candidate.assertion_id,)
    else:
        assert receipt.historical_assertion_ids == (candidate.assertion_id,)
    assert not receipt.incomplete


def test_receipt_rejects_decision_not_in_allowlist_on_deserialization():
    source = _source("想去杭州。")
    candidate = _candidate(
        source,
        "杭州",
        object_label="杭州",
        allowed_decisions=(
            AssertionDecision.AVOID,
            AssertionDecision.HISTORICAL,
        ),
    )
    challenge = _challenge([source], [candidate])
    receipt = _receipt(
        challenge,
        [source],
        [candidate],
        [
            AssertionDecisionInput(
                assertion_id=candidate.assertion_id,
                decision=AssertionDecision.AVOID,
            )
        ],
    )

    data = receipt.model_dump()
    data["decisions"][0]["decision"] = AssertionDecision.INCLUDE.value
    data["avoided_assertion_ids"] = ()
    data["included_assertion_ids"] = (candidate.assertion_id,)
    data["receipt_hash"] = ""
    with pytest.raises(ValidationError, match="not allowed"):
        ConfirmationReceipt.model_validate(data)


def test_receipt_rejects_tampered_allowlist_with_old_hash():
    source = _source("想去杭州。")
    candidate = _candidate(
        source,
        "杭州",
        object_label="杭州",
        allowed_decisions=(
            AssertionDecision.AVOID,
            AssertionDecision.HISTORICAL,
        ),
    )
    challenge = _challenge([source], [candidate])
    receipt = _receipt(
        challenge,
        [source],
        [candidate],
        [
            AssertionDecisionInput(
                assertion_id=candidate.assertion_id,
                decision=AssertionDecision.AVOID,
            )
        ],
    )

    data = receipt.model_dump()
    data["decisions"][0]["allowed_decisions"] = [
        AssertionDecision.INCLUDE.value,
        AssertionDecision.AVOID.value,
        AssertionDecision.HISTORICAL.value,
    ]
    data["receipt_hash"] = ""
    with pytest.raises(ValidationError, match="assertion_hash"):
        ConfirmationReceipt.model_validate(data)


@pytest.mark.parametrize(
    "tampered_allowlist",
    [
        [],
        ["include", "include"],
        ["unknown_decision"],
    ],
)
def test_receipt_rejects_invalid_allowlist_on_deserialization(
    tampered_allowlist,
) -> None:
    source = _source("想去杭州。")
    candidate = _candidate(source, "杭州", object_label="杭州")
    challenge = _challenge([source], [candidate])
    receipt = _receipt(
        challenge,
        [source],
        [candidate],
        [
            AssertionDecisionInput(
                assertion_id=candidate.assertion_id,
                decision=AssertionDecision.INCLUDE,
            )
        ],
    )

    data = receipt.model_dump()
    data["decisions"][0]["allowed_decisions"] = tampered_allowlist
    data["receipt_hash"] = ""
    with pytest.raises(ValidationError):
        ConfirmationReceipt.model_validate(data)


def test_quote_must_equal_exact_codepoint_span():
    source = _source("A🍜B 烤肉")
    quote = "🍜B"
    start = source.text.index("🍜")
    candidate = _candidate(source, quote, start=start)

    assert (candidate.span_start, candidate.span_end) == (start, start + 2)
    assert candidate.quote == source.text[start : start + 2]

    with pytest.raises(ConfirmationContractError, match="quote"):
        build_assertion_candidate(
            source=source,
            span_start=start,
            span_end=start + 2,
            quote="🍜",
            domain=RequirementDomain.FOOD,
            meaning=AssertionMeaning.INCLUDE,
            allowed_decisions=ALL_DECISIONS,
            object_label="面",
        )
    with pytest.raises(ConfirmationContractError, match="outside"):
        build_assertion_candidate(
            source=source,
            span_start=0,
            span_end=len(source.text) + 1,
            quote=source.text,
            domain=RequirementDomain.FOOD,
            meaning=AssertionMeaning.INCLUDE,
            allowed_decisions=ALL_DECISIONS,
            object_label="整段",
        )
    with pytest.raises(ConfirmationContractError, match="outside"):
        build_assertion_candidate(
            source=source,
            span_start=start,
            span_end=start,
            quote="",
            domain=RequirementDomain.FOOD,
            meaning=AssertionMeaning.INCLUDE,
            allowed_decisions=ALL_DECISIONS,
            object_label="空",
        )


def test_object_label_must_be_verbatim_substring_of_quote():
    source = _source("杭州旅行")
    substring = _candidate(source, "杭州", object_label="杭州")
    full = _candidate(source, "杭州旅行", object_label="杭州旅行")
    assert substring.object_label == "杭州"
    assert full.object_label == "杭州旅行"

    with pytest.raises(ConfirmationContractError, match="verbatim"):
        _candidate(source, "杭州", object_label="东京迪士尼")
    with pytest.raises(ConfirmationContractError, match="verbatim"):
        _candidate(source, "杭州", object_label="杭州旅行")

    payload = {
        "source_id": source.source_id,
        "source_hash": source.source_hash,
        "span_start": 0,
        "span_end": 2,
        "quote": "杭州",
        "domain": RequirementDomain.PLACE,
        "meaning": AssertionMeaning.INCLUDE,
        "allowed_decisions": ALL_DECISIONS,
        "object_label": "东京迪士尼",
    }
    with pytest.raises(ValidationError, match="object label"):
        AssertionCandidate.model_validate(payload)

    direct = AssertionCandidate.model_validate(
        {**payload, "object_label": "杭州"}
    )
    challenge = _challenge([source], [direct])
    assert challenge.assertion_digests[0].assertion_id == direct.assertion_id

    with pytest.raises(ValidationError, match="assertion"):
        direct.model_copy(update={"object_label": "东京迪士尼"})


@pytest.mark.parametrize(
    ("source_text", "object_label"),
    [
        (" 杭州", " 杭州"),
        ("杭州 ", "杭州 "),
        ("杭州", "   "),
        ("杭\t州", "杭\t州"),
        ("杭\n州", "杭\n州"),
        ("杭\u200b州", "杭\u200b州"),
        ("杭\x00州", "杭\x00州"),
        ("東京", "东京"),
        ("㍿", "株式会社"),
        ("ＡＢ", "AB"),
    ],
)
def test_object_label_rejects_forbidden_characters_and_normalization(
    source_text: str,
    object_label: str,
) -> None:
    source = _source(source_text)
    with pytest.raises(ConfirmationContractError, match="object label"):
        _candidate(source, source_text, object_label=object_label)

    payload = {
        "source_id": source.source_id,
        "source_hash": source.source_hash,
        "span_start": 0,
        "span_end": len(source_text),
        "quote": source_text,
        "domain": RequirementDomain.PLACE,
        "meaning": AssertionMeaning.INCLUDE,
        "allowed_decisions": ALL_DECISIONS,
        "object_label": object_label,
    }
    with pytest.raises(ValidationError, match="object label"):
        AssertionCandidate.model_validate(payload)


def test_multiword_international_destination_and_diet_labels_are_authorized():
    source = _source(
        "I want to visit New York and avoid peanut oil."
    )
    place = _candidate(
        source,
        "New York",
        object_label="New York",
        domain=RequirementDomain.PLACE,
    )
    diet = _candidate(
        source,
        "peanut oil",
        object_label="peanut oil",
        domain=RequirementDomain.FOOD,
        meaning=AssertionMeaning.EXCLUDE,
    )
    assert place.object_label == "New York"
    assert diet.object_label == "peanut oil"

    challenge = _challenge([source], [place, diet])
    receipt = _receipt(
        challenge,
        [source],
        [place, diet],
        [
            AssertionDecisionInput(
                assertion_id=place.assertion_id,
                decision=AssertionDecision.INCLUDE,
            ),
            AssertionDecisionInput(
                assertion_id=diet.assertion_id,
                decision=AssertionDecision.AVOID,
            ),
        ],
    )
    assert receipt.included_assertion_ids == (place.assertion_id,)
    assert receipt.avoided_assertion_ids == (diet.assertion_id,)
    assert not receipt.incomplete


def test_non_control_unicode_whitespace_inside_label_is_allowed():
    source = _source("Visit New\u00a0York and avoid peanut oil.")
    place = _candidate(
        source,
        "New\u00a0York",
        object_label="New\u00a0York",
        domain=RequirementDomain.PLACE,
    )
    assert place.object_label == "New\u00a0York"
    assert place.normalized_object == "new york"

    challenge = _challenge([source], [place])
    receipt = _receipt(
        challenge,
        [source],
        [place],
        [
            AssertionDecisionInput(
                assertion_id=place.assertion_id,
                decision=AssertionDecision.INCLUDE,
            )
        ],
    )
    assert receipt.included_assertion_ids == (place.assertion_id,)


def test_challenge_rechecks_direct_candidate_not_only_builder():
    source = _source("杭州旅行")
    payload = {
        "source_id": source.source_id,
        "source_hash": source.source_hash,
        "span_start": 0,
        "span_end": 2,
        "quote": "杭州",
        "domain": RequirementDomain.PLACE,
        "meaning": AssertionMeaning.INCLUDE,
        "allowed_decisions": ALL_DECISIONS,
        "object_label": "杭州",
    }
    direct = AssertionCandidate.model_validate(payload)
    challenge = _challenge([source], [direct])
    assert challenge.assertion_digests[0].assertion_id == direct.assertion_id

    forged = AssertionCandidate.model_construct(
        assertion_id=direct.assertion_id,
        source_id=direct.source_id,
        source_hash=direct.source_hash,
        span_start=direct.span_start,
        span_end=direct.span_end,
        quote=direct.quote,
        domain=direct.domain,
        meaning=direct.meaning,
        allowed_decisions=direct.allowed_decisions,
        object_label="东京迪士尼",
        normalized_object="东京迪士尼",
        assertion_hash=direct.assertion_hash,
    )
    with pytest.raises(ConfirmationContractError, match="object label"):
        _challenge([source], [forged])

    ghost_source = _source("成都", source_id="source_ghost")
    ghost = AssertionCandidate.model_validate(
        {
            "source_id": ghost_source.source_id,
            "source_hash": ghost_source.source_hash,
            "span_start": 0,
            "span_end": 2,
            "quote": "成都",
            "domain": RequirementDomain.PLACE,
            "meaning": AssertionMeaning.INCLUDE,
            "allowed_decisions": ALL_DECISIONS,
            "object_label": "成都",
        }
    )
    with pytest.raises(ConfirmationContractError, match="unknown source"):
        _challenge([source], [ghost])


def test_phantom_source_and_quote_fail_closed():
    real = _source("想去杭州。")
    real_candidate = _candidate(real, "杭州", object_label="杭州")

    ghost = _source(
        "想去成都。",
        source_id="source_ghost",
    )
    ghost_candidate = _candidate(ghost, "成都", object_label="成都")

    with pytest.raises(ConfirmationContractError, match="unknown source"):
        _challenge([real], [real_candidate, ghost_candidate])

    # 同一个 source_id 的文本发生变化时，旧候选随挑战一起失效。
    changed = _source("想去杭州吃烤肉。", source_id=real.source_id)
    with pytest.raises(ConfirmationContractError, match="revision"):
        _challenge([changed], [real_candidate])


def test_include_and_avoid_are_distinct_never_interchangeable():
    source = _source("想去杭州，避开西湖。")
    include = _candidate(
        source,
        "杭州",
        domain=RequirementDomain.PLACE,
        meaning=AssertionMeaning.INCLUDE,
    )
    avoid = _candidate(
        source,
        "西湖",
        domain=RequirementDomain.PLACE,
        meaning=AssertionMeaning.EXCLUDE,
    )
    challenge = _challenge([source], [include, avoid])

    receipt = _receipt(
        challenge,
        [source],
        [include, avoid],
        [
            AssertionDecisionInput(
                assertion_id=include.assertion_id,
                decision=AssertionDecision.INCLUDE,
            ),
            AssertionDecisionInput(
                assertion_id=avoid.assertion_id,
                decision=AssertionDecision.AVOID,
            ),
        ],
    )

    assert receipt.included_assertion_ids == (include.assertion_id,)
    assert receipt.avoided_assertion_ids == (avoid.assertion_id,)
    assert not receipt.incomplete
    assert not set(receipt.included_assertion_ids) & set(
        receipt.avoided_assertion_ids
    )


def test_model_labels_do_not_decide_the_receipt():
    source = _source("不要烤肉。")
    candidate = _candidate(
        source,
        "不要烤肉",
        object_label="烤肉",
        meaning=AssertionMeaning.INCLUDE,
    )
    challenge = _challenge([source], [candidate])

    receipt = _receipt(
        challenge,
        [source],
        [candidate],
        [
            AssertionDecisionInput(
                assertion_id=candidate.assertion_id,
                decision=AssertionDecision.AVOID,
            )
        ],
    )

    assert receipt.avoided_assertion_ids == (candidate.assertion_id,)
    assert receipt.included_assertion_ids == ()


def test_saved_preference_and_trip_context_cannot_be_positive():
    saved = _source(
        "我一直喜欢川菜。",
        kind=SourceKind.SAVED_PREFERENCE,
        source_id="source_saved",
    )
    saved_candidate = _candidate(saved, "川菜", object_label="川菜")
    saved_challenge = _challenge([saved], [saved_candidate])

    for decision in (AssertionDecision.INCLUDE, AssertionDecision.AVOID):
        with pytest.raises(ConfirmationRejected, match="re-entered"):
            _receipt(
                saved_challenge,
                [saved],
                [saved_candidate],
                [
                    AssertionDecisionInput(
                        assertion_id=saved_candidate.assertion_id,
                        decision=decision,
                    )
                ],
            )

    historical = _receipt(
        saved_challenge,
        [saved],
        [saved_candidate],
        [
            AssertionDecisionInput(
                assertion_id=saved_candidate.assertion_id,
                decision=AssertionDecision.HISTORICAL,
            )
        ],
    )
    assert historical.historical_assertion_ids == (saved_candidate.assertion_id,)
    assert historical.included_assertion_ids == ()
    assert historical.avoided_assertion_ids == ()
    assert not historical.incomplete

    trip = _source(
        "上一次旅行去过成都。",
        kind=SourceKind.TRIP_CONTEXT,
        source_id="source_trip",
    )
    trip_candidate = _candidate(trip, "成都", object_label="成都")
    trip_challenge = _challenge([trip], [trip_candidate])

    with pytest.raises(ConfirmationRejected, match="re-entered"):
        _receipt(
            trip_challenge,
            [trip],
            [trip_candidate],
            [
                AssertionDecisionInput(
                    assertion_id=trip_candidate.assertion_id,
                    decision=AssertionDecision.INCLUDE,
                )
            ],
        )

    unknown = _receipt(
        trip_challenge,
        [trip],
        [trip_candidate],
        [
            AssertionDecisionInput(
                assertion_id=trip_candidate.assertion_id,
                decision=AssertionDecision.UNKNOWN,
            )
        ],
    )
    assert unknown.incomplete
    assert unknown.unknown_assertion_ids == (trip_candidate.assertion_id,)
    assert unknown.included_assertion_ids == ()
    assert unknown.avoided_assertion_ids == ()


def test_same_normalized_object_conflicts_across_domains():
    source = _source("避开咖啡，安排咖啡活动。")
    avoid = _candidate(
        source,
        "咖啡",
        object_label="咖啡",
        domain=RequirementDomain.FOOD,
    )
    include = _candidate(
        source,
        "咖啡活动",
        object_label="咖啡",
        domain=RequirementDomain.ACTIVITY,
        start=source.text.index("咖啡活动"),
    )
    assert avoid.normalized_object == include.normalized_object == "咖啡"
    assert avoid.domain is not include.domain

    challenge = _challenge([source], [avoid, include])
    with pytest.raises(ConfirmationRejected, match="same normalized object"):
        _receipt(
            challenge,
            [source],
            [avoid, include],
            [
                AssertionDecisionInput(
                    assertion_id=avoid.assertion_id,
                    decision=AssertionDecision.AVOID,
                ),
                AssertionDecisionInput(
                    assertion_id=include.assertion_id,
                    decision=AssertionDecision.INCLUDE,
                ),
            ],
        )


def test_missing_duplicate_unknown_and_stale_and_cross_run_are_rejected():
    source = _source("想去杭州，避开西湖。")
    first = _candidate(source, "杭州", object_label="杭州")
    second = _candidate(source, "西湖", object_label="西湖")
    challenge = _challenge([source], [first, second])

    include_first = AssertionDecisionInput(
        assertion_id=first.assertion_id,
        decision=AssertionDecision.INCLUDE,
    )
    avoid_second = AssertionDecisionInput(
        assertion_id=second.assertion_id,
        decision=AssertionDecision.AVOID,
    )

    with pytest.raises(ConfirmationRejected, match="missing"):
        _receipt(challenge, [source], [first, second], [include_first])
    with pytest.raises(ConfirmationRejected, match="duplicate"):
        _receipt(
            challenge,
            [source],
            [first, second],
            [include_first, include_first, avoid_second],
        )
    with pytest.raises(ConfirmationRejected, match="unknown assertion"):
        _receipt(
            challenge,
            [source],
            [first, second],
            [
                include_first,
                AssertionDecisionInput(
                    assertion_id="assertion_not_server_owned",
                    decision=AssertionDecision.UNKNOWN,
                ),
            ],
        )

    next_challenge = _challenge(
        [source],
        [first, second],
        revision=2,
        previous=challenge,
    )
    assert next_challenge.token != challenge.token
    with pytest.raises(ConfirmationRejected, match="stale"):
        _receipt(
            next_challenge,
            [source],
            [first, second],
            [include_first, avoid_second],
            token=challenge.token,
        )

    for field, value, match in (
        ("run_id", "run_other", "different run"),
        ("session_id", "session_other", "different session"),
        ("identity_hash", hashlib.sha256(b"other").hexdigest(), "identity"),
        ("policy_version", "policy_other", "policy"),
    ):
        kwargs = {field: value}
        with pytest.raises(ConfirmationRejected, match=match):
            _receipt(
                challenge,
                [source],
                [first, second],
                [include_first, avoid_second],
                **kwargs,
            )

    with pytest.raises(ConfirmationContractError, match="same run/session"):
        _challenge(
            [source],
            [first, second],
            revision=2,
            run_id="run_other",
            previous=challenge,
        )


def test_stable_replay_and_monotonic_revision():
    source = _source("想去杭州，避开西湖。")
    first = _candidate(source, "杭州", object_label="杭州")
    second = _candidate(source, "西湖", object_label="西湖")

    first_challenge = _challenge([source], [first, second])
    replay_challenge = _challenge([source], [first, second])
    assert first_challenge == replay_challenge
    assert first_challenge.token == replay_challenge.token

    decisions = [
        AssertionDecisionInput(
            assertion_id=first.assertion_id,
            decision=AssertionDecision.INCLUDE,
        ),
        AssertionDecisionInput(
            assertion_id=second.assertion_id,
            decision=AssertionDecision.AVOID,
        ),
    ]
    first_receipt = _receipt(
        first_challenge,
        [source],
        [first, second],
        decisions,
    )
    replay_receipt = _receipt(
        replay_challenge,
        [source],
        [first, second],
        list(reversed(decisions)),
    )
    assert first_receipt == replay_receipt
    assert first_receipt.receipt_hash == replay_receipt.receipt_hash

    next_challenge = _challenge(
        [source],
        [first, second],
        revision=first_challenge.revision + 1,
        previous=first_challenge,
    )
    assert next_challenge.revision > first_challenge.revision
    assert next_challenge.token != first_challenge.token

    with pytest.raises(ConfirmationContractError, match="strictly increase"):
        _challenge(
            [source],
            [first, second],
            revision=first_challenge.revision,
            previous=first_challenge,
        )


def test_complete_valid_receipt_contains_full_source_context():
    current = _source(
        "当前请求：想在杭州吃烤肉。",
        source_id="source_current",
    )
    supplement = _source(
        "补充：不吃香菜。",
        kind=SourceKind.EXPLICIT_SUPPLEMENT,
        source_id="source_supplement",
    )
    form = _source(
        "表单：需要无障碍安排。",
        kind=SourceKind.STRUCTURED_FORM,
        source_id="source_form",
    )
    keep = _candidate(
        current,
        "杭州",
        object_label="杭州",
        domain=RequirementDomain.PLACE,
    )
    avoid = _candidate(
        supplement,
        "香菜",
        object_label="香菜",
        domain=RequirementDomain.FOOD,
        meaning=AssertionMeaning.EXCLUDE,
    )
    historical = _candidate(
        form,
        "无障碍安排",
        object_label="无障碍安排",
        domain=RequirementDomain.ACCESSIBILITY,
        meaning=AssertionMeaning.CONSTRAINT,
    )

    sources = [current, supplement, form]
    assertions = [keep, avoid, historical]
    challenge = _challenge(sources, assertions)
    receipt = _receipt(
        challenge,
        sources,
        assertions,
        [
            AssertionDecisionInput(
                assertion_id=keep.assertion_id,
                decision=AssertionDecision.INCLUDE,
            ),
            AssertionDecisionInput(
                assertion_id=avoid.assertion_id,
                decision=AssertionDecision.AVOID,
            ),
            AssertionDecisionInput(
                assertion_id=historical.assertion_id,
                decision=AssertionDecision.HISTORICAL,
            ),
        ],
    )

    assert not receipt.incomplete
    assert receipt.included_assertion_ids == (keep.assertion_id,)
    assert receipt.avoided_assertion_ids == (avoid.assertion_id,)
    assert receipt.historical_assertion_ids == (historical.assertion_id,)
    assert receipt.unknown_assertion_ids == ()
    assert {source.source_id for source in receipt.sources} == {
        "source_current",
        "source_supplement",
        "source_form",
    }
    assert {source.text for source in receipt.sources} == {
        current.text,
        supplement.text,
        form.text,
    }
    assert receipt.receipt_hash
    assert receipt.model_dump()["incomplete"] is False

    # 冻结模型不能被就地篡改。
    with pytest.raises(ValidationError):
        receipt.incomplete = True


def test_unknown_is_explicitly_incomplete_and_never_positive():
    source = _source("可能想去杭州。")
    candidate = _candidate(source, "杭州", object_label="杭州")
    challenge = _challenge([source], [candidate])

    receipt = _receipt(
        challenge,
        [source],
        [candidate],
        [
            AssertionDecisionInput(
                assertion_id=candidate.assertion_id,
                decision=AssertionDecision.UNKNOWN,
            )
        ],
    )

    assert receipt.incomplete
    assert receipt.unknown_assertion_ids == (candidate.assertion_id,)
    assert receipt.included_assertion_ids == ()
    assert receipt.avoided_assertion_ids == ()
    assert receipt.historical_assertion_ids == ()


def test_receipt_rejects_tampered_deserialization_and_model_copy():
    source = _source("杭州旅行")
    candidate = _candidate(source, "杭州", object_label="杭州")
    challenge = _challenge([source], [candidate])
    receipt = _receipt(
        challenge,
        [source],
        [candidate],
        [
            AssertionDecisionInput(
                assertion_id=candidate.assertion_id,
                decision=AssertionDecision.INCLUDE,
            )
        ],
    )

    assert ConfirmationReceipt.model_validate(receipt.model_dump()) == receipt
    assert receipt.model_copy() == receipt

    with pytest.raises(ValidationError, match="incomplete"):
        receipt.model_copy(update={"incomplete": True})
    with pytest.raises(ValidationError):
        receipt.model_copy(
            update={"included_assertion_ids": ("assertion_injected",)}
        )
    with pytest.raises(ValidationError):
        receipt.model_copy(update={"challenge_token": "challenge_" + "0" * 64})
    with pytest.raises(ValidationError):
        receipt.decisions[0].model_copy(
            update={"object_label": "东京迪士尼"}
        )
    with pytest.raises(ValidationError):
        source.model_copy(update={"text": "杭州"})
    with pytest.raises(ValidationError):
        candidate.model_copy(update={"object_label": "东京迪士尼"})

    data = receipt.model_dump()
    data["incomplete"] = True
    with pytest.raises(ValidationError):
        ConfirmationReceipt.model_validate(data)

    data = receipt.model_dump()
    data["included_assertion_ids"] = ("assertion_injected",)
    with pytest.raises(ValidationError):
        ConfirmationReceipt.model_validate(data)

    data = receipt.model_dump()
    data["sources"][0]["text"] = "杭州"
    with pytest.raises(ValidationError):
        ConfirmationReceipt.model_validate(data)

    data = receipt.model_dump()
    data["decisions"][0]["object_label"] = "东京迪士尼"
    with pytest.raises(ValidationError):
        ConfirmationReceipt.model_validate(data)

    data = receipt.model_dump()
    data["challenge_token"] = "challenge_" + "0" * 64
    with pytest.raises(ValidationError):
        ConfirmationReceipt.model_validate(data)


def test_receipt_rejects_swapped_decision_groups_on_deserialization():
    source = _source("I want to visit New York and avoid peanut oil.")
    place = _candidate(
        source,
        "New York",
        object_label="New York",
        domain=RequirementDomain.PLACE,
    )
    diet = _candidate(
        source,
        "peanut oil",
        object_label="peanut oil",
        domain=RequirementDomain.FOOD,
        meaning=AssertionMeaning.EXCLUDE,
    )
    challenge = _challenge([source], [place, diet])
    receipt = _receipt(
        challenge,
        [source],
        [place, diet],
        [
            AssertionDecisionInput(
                assertion_id=place.assertion_id,
                decision=AssertionDecision.INCLUDE,
            ),
            AssertionDecisionInput(
                assertion_id=diet.assertion_id,
                decision=AssertionDecision.AVOID,
            ),
        ],
    )

    data = receipt.model_dump()
    data["included_assertion_ids"], data["avoided_assertion_ids"] = (
        data["avoided_assertion_ids"],
        data["included_assertion_ids"],
    )
    data["receipt_hash"] = ""
    with pytest.raises(ValidationError, match="decision groups"):
        ConfirmationReceipt.model_validate(data)


def test_receipt_rejects_relabelled_record_with_stale_assertion_hash():
    source = _source("杭州西湖")
    candidate = _candidate(
        source,
        "杭州西湖",
        object_label="杭州",
        domain=RequirementDomain.PLACE,
    )
    challenge = _challenge([source], [candidate])
    receipt = _receipt(
        challenge,
        [source],
        [candidate],
        [
            AssertionDecisionInput(
                assertion_id=candidate.assertion_id,
                decision=AssertionDecision.INCLUDE,
            )
        ],
    )

    data = receipt.model_dump()
    data["decisions"][0]["object_label"] = "西湖"
    data["decisions"][0]["normalized_object"] = "西湖"
    data["receipt_hash"] = ""
    with pytest.raises(ValidationError, match="assertion_hash"):
        ConfirmationReceipt.model_validate(data)


@pytest.mark.parametrize(
    "kind",
    [SourceKind.SAVED_PREFERENCE, SourceKind.TRIP_CONTEXT],
)
@pytest.mark.parametrize(
    "decision",
    [AssertionDecision.INCLUDE, AssertionDecision.AVOID],
)
def test_receipt_rejects_non_authorizing_positive_on_deserialization(
    kind: SourceKind,
    decision: AssertionDecision,
) -> None:
    source = _source(
        "我喜欢川菜。",
        kind=kind,
        source_id=f"source_{kind.value}",
    )
    candidate = _candidate(source, "川菜", object_label="川菜")
    challenge = _challenge([source], [candidate])
    receipt = _receipt(
        challenge,
        [source],
        [candidate],
        [
            AssertionDecisionInput(
                assertion_id=candidate.assertion_id,
                decision=AssertionDecision.HISTORICAL,
            )
        ],
    )

    data = receipt.model_dump()
    data["decisions"][0]["decision"] = decision.value
    data["historical_assertion_ids"] = ()
    data["included_assertion_ids"] = (
        (candidate.assertion_id,)
        if decision is AssertionDecision.INCLUDE
        else ()
    )
    data["avoided_assertion_ids"] = (
        (candidate.assertion_id,)
        if decision is AssertionDecision.AVOID
        else ()
    )
    data["receipt_hash"] = ""
    with pytest.raises(ValidationError, match="re-entered"):
        ConfirmationReceipt.model_validate(data)


def test_receipt_rejects_same_object_conflict_on_deserialization():
    source = _source("想吃烤肉，也不想吃烤肉。")
    first = _candidate(
        source,
        "想吃烤肉",
        object_label="烤肉",
        domain=RequirementDomain.FOOD,
    )
    second = _candidate(
        source,
        "不想吃烤肉",
        object_label="烤肉",
        domain=RequirementDomain.FOOD,
    )
    challenge = _challenge([source], [first, second])
    receipt = _receipt(
        challenge,
        [source],
        [first, second],
        [
            AssertionDecisionInput(
                assertion_id=first.assertion_id,
                decision=AssertionDecision.INCLUDE,
            ),
            AssertionDecisionInput(
                assertion_id=second.assertion_id,
                decision=AssertionDecision.HISTORICAL,
            ),
        ],
    )

    data = receipt.model_dump()
    target = next(
        index
        for index, record in enumerate(data["decisions"])
        if record["assertion_id"] == second.assertion_id
    )
    data["decisions"][target]["decision"] = AssertionDecision.AVOID.value
    data["historical_assertion_ids"] = ()
    data["avoided_assertion_ids"] = (second.assertion_id,)
    data["receipt_hash"] = ""
    with pytest.raises(ValidationError, match="same normalized object"):
        ConfirmationReceipt.model_validate(data)


def test_receipt_rejects_cross_domain_conflict_on_deserialization():
    source = _source("避开咖啡，安排咖啡活动。")
    avoid = _candidate(
        source,
        "咖啡",
        object_label="咖啡",
        domain=RequirementDomain.FOOD,
    )
    include = _candidate(
        source,
        "咖啡活动",
        object_label="咖啡",
        domain=RequirementDomain.ACTIVITY,
        start=source.text.index("咖啡活动"),
    )
    challenge = _challenge([source], [avoid, include])
    receipt = _receipt(
        challenge,
        [source],
        [avoid, include],
        [
            AssertionDecisionInput(
                assertion_id=avoid.assertion_id,
                decision=AssertionDecision.HISTORICAL,
            ),
            AssertionDecisionInput(
                assertion_id=include.assertion_id,
                decision=AssertionDecision.INCLUDE,
            ),
        ],
    )

    data = receipt.model_dump()
    target = next(
        index
        for index, record in enumerate(data["decisions"])
        if record["assertion_id"] == avoid.assertion_id
    )
    data["decisions"][target]["decision"] = AssertionDecision.AVOID.value
    data["historical_assertion_ids"] = ()
    data["avoided_assertion_ids"] = (avoid.assertion_id,)
    data["receipt_hash"] = ""
    with pytest.raises(ValidationError, match="same normalized object"):
        ConfirmationReceipt.model_validate(data)


def test_no_default_or_yes_all_decisions():
    assert "decision" in AssertionDecisionInput.model_fields
    assert AssertionDecisionInput.model_fields["decision"].is_required()
    with pytest.raises(ValidationError):
        AssertionDecisionInput(assertion_id="assertion_x")  # type: ignore[call-arg]

    source = _source("想去杭州。")
    candidate = _candidate(source, "杭州", object_label="杭州")
    challenge = _challenge([source], [candidate])
    with pytest.raises(ConfirmationRejected, match="explicit decision"):
        _receipt(challenge, [source], [candidate], [])
