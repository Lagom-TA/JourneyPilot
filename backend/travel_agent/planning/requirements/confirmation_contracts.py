"""服务端权威的语义需求确认契约。

本模块只提供确认流程的底层原语，不接入 planner、API 或持久化层。
它刻意把「模型提出了什么」和「用户确认了什么」分开：

* ``SourceEvidence`` 由服务端持有，保存完整原文；候选断言只能引用原文中的
  精确码点区间，不能自己编造文本或来源。可选 ``context`` 只是显示上下文，
  不能用于引用匹配，但会进入来源摘要和确认挑战/回执。
* ``AssertionCandidate`` 的 ``object_label`` 必须是所引用 quote 中逐字、连续的
  原始子串；``domain`` / ``meaning`` 是受控标签，只用于展示和摘要绑定，不参与
  从文本推断极性，也不能代替用户决定。
* ``AssertionCandidate.allowed_decisions`` 是服务器提供的非空、无重复 allowlist，
  并进入 assertion hash；回执会逐项拒绝不在该列表中的用户决定。
* 可选 ``RequirementExecution`` 保存确认后实际执行所需的结构化字段；非空时其
  完整 JSON 进入 assertion ID/hash，工作流之外不强制它存在。
* ``ConfirmationChallenge`` 把一次待确认集合绑定到 run/session、身份、策略、
  服务端 candidate_contract_hash 和摘要上；``ConfirmationReceipt`` 只从服务端
  挑战和用户提交的 ``{assertion_id, decision}`` 构造。缺少
  candidate_contract_hash 的旧 challenge/receipt 不会被自动升级。
* 保存的偏好与行程上下文属于非授权来源，必须由用户在当前请求/补充/表单中
  重新输入后才能成为正向授权。
* ``explicit_selection`` 的选项标签由模型提议；它的 include/avoid 只有在
  current_request / explicit_supplement / 已核实 structured_form 的 text 中
  也逐字出现同一对象时才可直接授权，否则 fail-closed。
* ``unknown`` 永远只产生 incomplete 回执，不会被算作 include/avoid。

这里没有关键词极性表，也没有「全部同意」默认值：每个断言都必须显式给出
``include``、``avoid``、``historical``、``unknown`` 之一。本模块不证明模型语义
理解、个人健康或医学安全，只约束来源绑定、用户决定和摘要一致性。
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from enum import Enum
from typing import Any
from typing import Dict, Iterable
from typing import List
from typing import Literal
from typing import Optional
from typing import Sequence
from typing import Tuple

from pydantic import Field
from pydantic import ValidationError
from pydantic import field_validator
from pydantic import model_validator

from travel_agent.schema import StrictModel


CONFIRMATION_CONTRACT_VERSION = "journeypilot.confirmation_contract.v1"

MAX_SOURCE_CHARS = 20_000
MAX_CONTEXT_CHARS = 4_000
MAX_QUOTE_CHARS = 500
MAX_OBJECT_LABEL_CHARS = 200
MAX_SOURCES = 64
MAX_ASSERTIONS = 128
MAX_DECISIONS = MAX_ASSERTIONS
MAX_EXECUTION_ID_CHARS = 128
MAX_EXECUTION_KIND_CHARS = 64
MAX_EXECUTION_TARGET_CHARS = 200
MAX_EXECUTION_APPLIES_TO = 32
MAX_EXECUTION_APPLIES_TO_ITEM_CHARS = 128
MAX_EXECUTION_SCOPE_CHARS = 128
MAX_EXECUTION_PUBLIC_SUMMARY_CHARS = 500
MAX_EXECUTION_VALUE_DEPTH = 8
MAX_EXECUTION_VALUE_CHARS = 8_000
MAX_EXECUTION_VALUE_ITEMS = 256
MAX_EXECUTION_VALUE_STRING_CHARS = 2_000

_DIGEST_PATTERN = r"^[0-9a-f]{64}$"
_OPTIONAL_DIGEST_PATTERN = r"^(?:[0-9a-f]{64})?$"
_TOKEN_PATTERN = r"^challenge_[0-9a-f]{64}$"


class ConfirmationContractError(ValueError):
    """确认契约拒绝了一次不满足约束的构造或提交。"""


class ConfirmationRejected(ConfirmationContractError):
    """回执构造被服务端拒绝。"""


class _SealedContractModel(StrictModel):
    """复制时重新走校验，避免 ``model_copy(update=...)`` 绕过摘要检查。"""

    def model_copy(
        self,
        *,
        update: Optional[Dict[str, object]] = None,
        deep: bool = False,
    ) -> "_SealedContractModel":
        data = self.model_dump(mode="python")
        if update:
            data.update(update)
        return type(self).model_validate(data)


class SourceKind(str, Enum):
    CURRENT_REQUEST = "current_request"
    EXPLICIT_SUPPLEMENT = "explicit_supplement"
    STRUCTURED_FORM = "structured_form"
    EXPLICIT_SELECTION = "explicit_selection"
    SAVED_PREFERENCE = "saved_preference"
    TRIP_CONTEXT = "trip_context"


# 这些来源只能作为审阅上下文，不能被本次提交直接转成正向授权。
NON_AUTHORIZING_SOURCE_KINDS = frozenset(
    {SourceKind.SAVED_PREFERENCE, SourceKind.TRIP_CONTEXT}
)

# 选项标签由模型提议；只有这些独立来源的 text 也逐字包含同一对象时，
# 本轮才能把 selection 的 include/avoid 直接当作授权。
# structured_form 视为 intake 已核实的结构化来源。
SELECTION_EVIDENCE_SOURCE_KINDS = frozenset(
    {
        SourceKind.CURRENT_REQUEST,
        SourceKind.EXPLICIT_SUPPLEMENT,
        SourceKind.STRUCTURED_FORM,
    }
)


class RequirementDomain(str, Enum):
    """受控需求域；它不是从原文关键词推导出来的。"""

    PLACE = "place"
    ACTIVITY = "activity"
    FOOD = "food"
    ACCOMMODATION = "accommodation"
    TRANSPORT = "transport"
    PACE = "pace"
    BUDGET = "budget"
    ACCESSIBILITY = "accessibility"
    SCHEDULE = "schedule"
    CONSTRAINT = "constraint"
    OUTPUT = "output"


class AssertionMeaning(str, Enum):
    """模型对候选语义的受控描述；最终决定仍由用户显式提交。"""

    INCLUDE = "include"
    EXCLUDE = "exclude"
    PREFERENCE = "preference"
    CONSTRAINT = "constraint"
    CONTEXT = "context"


class AssertionDecision(str, Enum):
    INCLUDE = "include"
    AVOID = "avoid"
    HISTORICAL = "historical"
    UNKNOWN = "unknown"


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _enum_value(value: object) -> object:
    return value.value if isinstance(value, Enum) else value


def _normalize_allowed_decisions(
    value: object,
) -> Optional[Tuple[AssertionDecision, ...]]:
    """归一化服务器提供的 decision allowlist；返回 None 交给 Pydantic 报错。"""

    if not isinstance(value, (list, tuple, set, frozenset)):
        return None
    try:
        decisions = tuple(
            item
            if isinstance(item, AssertionDecision)
            else AssertionDecision(item)
            for item in value
        )
    except (TypeError, ValueError):
        return None
    if not decisions:
        raise ValueError("allowed_decisions must not be empty")
    if len(set(decisions)) != len(decisions):
        raise ValueError("allowed_decisions must not contain duplicates")
    return tuple(sorted(decisions, key=lambda item: item.value))


def _assert_allowed_decisions(
    decisions: Sequence[AssertionDecision],
) -> None:
    try:
        normalized = _normalize_allowed_decisions(decisions)
    except ValueError as exc:
        raise ConfirmationContractError(str(exc)) from exc
    if normalized is None or tuple(normalized) != tuple(decisions):
        raise ConfirmationContractError(
            "allowed_decisions must be unique known decisions"
        )


def normalize_object_label(value: str) -> str:
    """确定性地归一化对象标签，不做同义词或语义归并。"""

    normalized = unicodedata.normalize("NFKC", value)
    normalized = " ".join(normalized.split())
    return normalized.casefold()


def _has_forbidden_label_character(value: str) -> bool:
    for character in value:
        if unicodedata.category(character).startswith("C"):
            return True
    return False


def _assert_json_value(value: object, *, depth: int = 0) -> int:
    """只接受 JSON 类型和有限数字；返回节点数。"""

    if depth > MAX_EXECUTION_VALUE_DEPTH:
        raise ConfirmationContractError(
            "execution value exceeds maximum depth"
        )
    if value is None or isinstance(value, bool):
        return 1
    if isinstance(value, int):
        return 1
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ConfirmationContractError(
                "execution value numbers must be finite"
            )
        return 1
    if isinstance(value, str):
        if len(value) > MAX_EXECUTION_VALUE_STRING_CHARS:
            raise ConfirmationContractError(
                "execution value string is too long"
            )
        return 1
    if isinstance(value, list):
        if len(value) > MAX_EXECUTION_VALUE_ITEMS:
            raise ConfirmationContractError(
                "execution value has too many items"
            )
        total = 1
        for item in value:
            total += _assert_json_value(item, depth=depth + 1)
            if total > MAX_EXECUTION_VALUE_ITEMS:
                raise ConfirmationContractError(
                    "execution value has too many items"
                )
        return total
    if isinstance(value, dict):
        if len(value) > MAX_EXECUTION_VALUE_ITEMS:
            raise ConfirmationContractError(
                "execution value has too many items"
            )
        total = 1
        for key, item in value.items():
            if not isinstance(key, str):
                raise ConfirmationContractError(
                    "execution value keys must be strings"
                )
            if not key or len(key) > MAX_EXECUTION_VALUE_STRING_CHARS:
                raise ConfirmationContractError(
                    "execution value key is invalid"
                )
            total += 1 + _assert_json_value(item, depth=depth + 1)
            if total > MAX_EXECUTION_VALUE_ITEMS:
                raise ConfirmationContractError(
                    "execution value has too many items"
                )
        return total
    raise ConfirmationContractError(
        "execution value must contain only JSON values"
    )


class RequirementExecution(_SealedContractModel):
    """确认后实际执行所需的结构化字段；完整内容进入 assertion 摘要。"""

    requirement_id: str = Field(
        min_length=1,
        max_length=MAX_EXECUTION_ID_CHARS,
    )
    requirement_type: Literal["intent", "constraint"]
    kind: str = Field(min_length=1, max_length=MAX_EXECUTION_KIND_CHARS)
    target: str = Field(min_length=1, max_length=MAX_EXECUTION_TARGET_CHARS)
    polarity: Literal["include", "exclude", "neutral"]
    strength: Literal["hard", "soft", "informational"]
    value: Dict[str, Any]
    applies_to: Tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_EXECUTION_APPLIES_TO,
    )
    scope: str = Field(min_length=1, max_length=MAX_EXECUTION_SCOPE_CHARS)
    public_summary: str = Field(
        min_length=1,
        max_length=MAX_EXECUTION_PUBLIC_SUMMARY_CHARS,
    )

    @field_validator("applies_to")
    @classmethod
    def _validate_applies_to(cls, value: Tuple[str, ...]) -> Tuple[str, ...]:
        for item in value:
            if not item.strip():
                raise ValueError("applies_to must not contain blank values")
            if len(item) > MAX_EXECUTION_APPLIES_TO_ITEM_CHARS:
                raise ValueError("applies_to entry is too long")
        return value

    @model_validator(mode="after")
    def _validate_value(self) -> "RequirementExecution":
        _assert_json_value(self.value)
        try:
            encoded = json.dumps(
                self.value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "execution value must be JSON-compatible"
            ) from exc
        if len(encoded) > MAX_EXECUTION_VALUE_CHARS:
            raise ValueError("execution value is too large")
        return self


def _execution_payload(execution: object) -> Optional[Dict[str, object]]:
    if execution is None:
        return None
    if isinstance(execution, RequirementExecution):
        data = execution.model_dump(mode="python")
    elif isinstance(execution, dict):
        data = dict(execution)
    else:
        raise ConfirmationContractError(
            "execution must be a requirement execution"
        )
    try:
        model = RequirementExecution.model_validate(data)
    except ValidationError as exc:
        raise ConfirmationContractError(
            "invalid requirement execution"
        ) from exc
    return model.model_dump(mode="json")


def assert_object_label_bound(object_label: str, quote: str) -> None:
    """对象标签必须是 quote 中逐字、连续的原始子串。

    内部普通空格和非控制 Unicode 空白可以出现在多词地点或饮食标签中，例如
    ``New York`` 或 ``peanut oil``；但标签不能全为空白、不能有首尾空白，也
    不能包含控制/格式字符。这里不做 NFKC、大小写折叠、同音字替换或空白压缩，
    因此不能靠归一化拼接让标签通过来源绑定。
    """

    if not object_label:
        raise ConfirmationContractError("object label must not be empty")
    if not object_label.strip():
        raise ConfirmationContractError("object label must not be all whitespace")
    if object_label[0].isspace() or object_label[-1].isspace():
        raise ConfirmationContractError(
            "object label must not have leading or trailing whitespace"
        )
    if _has_forbidden_label_character(object_label):
        raise ConfirmationContractError(
            "object label must not contain control or format characters"
        )
    if object_label not in quote:
        raise ConfirmationContractError(
            "object label must be a verbatim substring of the referenced quote"
        )


def _source_payload(
    *,
    source_id: str,
    kind: object,
    text: str,
    revision: int,
    context: Optional[str],
) -> Dict[str, object]:
    return {
        "schema_version": CONFIRMATION_CONTRACT_VERSION,
        "source_id": source_id,
        "kind": _enum_value(kind),
        "text": text,
        "revision": revision,
        # 展示用问题全文；它不参与引用区间匹配，但必须绑定摘要。
        "context": context,
    }


def _assertion_core_payload(
    *,
    source_id: str,
    source_hash: str,
    span_start: int,
    span_end: int,
    quote: str,
    domain: object,
    meaning: object,
    allowed_decisions: Sequence[AssertionDecision],
    object_label: str,
    normalized_object: str,
    execution: object = None,
) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "schema_version": CONFIRMATION_CONTRACT_VERSION,
        "source_id": source_id,
        "source_hash": source_hash,
        "span_start": span_start,
        "span_end": span_end,
        "quote": quote,
        "domain": _enum_value(domain),
        "meaning": _enum_value(meaning),
        "allowed_decisions": [
            _enum_value(item) for item in allowed_decisions
        ],
        "object_label": object_label,
        "normalized_object": normalized_object,
    }
    execution_payload = _execution_payload(execution)
    if execution_payload is not None:
        payload["execution"] = execution_payload
    return payload


class SourceEvidence(_SealedContractModel):
    """服务端持有的完整来源文本。

    ``text`` 是候选唯一可引用的证据区间来源；``context`` 只是展示给用户的
    问题/上下文全文，不能用来定位 quote 或 object。两者都进入 ``source_hash``。
    """

    source_id: str = Field(min_length=1, max_length=128)
    kind: SourceKind
    text: str = Field(min_length=1, max_length=MAX_SOURCE_CHARS)
    revision: int = Field(ge=0)
    context: Optional[str] = Field(
        default=None,
        max_length=MAX_CONTEXT_CHARS,
    )
    source_hash: str = Field(default="", pattern=_DIGEST_PATTERN)

    @model_validator(mode="before")
    @classmethod
    def _seal_source(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        values = dict(data)
        source_id = values.get("source_id")
        text = values.get("text")
        revision = values.get("revision")
        if not isinstance(source_id, str) or not isinstance(text, str):
            return values
        expected = _canonical_hash(
            _source_payload(
                source_id=source_id,
                kind=values.get("kind"),
                text=text,
                revision=revision,
                context=values.get("context"),
            )
        )
        supplied = values.get("source_hash")
        if supplied not in (None, "", expected):
            raise ValueError("source_hash does not match source content")
        values["source_hash"] = expected
        return values


def assert_source_integrity(source: SourceEvidence) -> None:
    """复核 ``SourceEvidence`` 的全文摘要，防止复制时只改正文。"""

    expected = _canonical_hash(
        _source_payload(
            source_id=source.source_id,
            kind=source.kind,
            text=source.text,
            revision=source.revision,
            context=source.context,
        )
    )
    if source.source_hash != expected:
        raise ConfirmationContractError(
            "source_hash does not match source content"
        )


def _has_independent_selection_evidence(
    object_label: str,
    sources: Sequence[SourceEvidence],
) -> bool:
    """selection 的对象是否逐字出现在独立来源的 text 中。

    只看 ``source.text``，绝不把 ``context`` 当证据；也不对通用词做领域
    特判或正向默认。
    """

    return any(
        source.kind in SELECTION_EVIDENCE_SOURCE_KINDS
        and object_label in source.text
        for source in sources
    )


def assert_quote_span(
    source: SourceEvidence,
    *,
    span_start: int,
    span_end: int,
    quote: str,
) -> None:
    """验证候选引用的是来源中的精确非空码点区间。"""

    if (
        isinstance(span_start, bool)
        or isinstance(span_end, bool)
        or not isinstance(span_start, int)
        or not isinstance(span_end, int)
    ):
        raise ConfirmationContractError("span is not an integer range")
    if span_start < 0 or span_end > len(source.text) or span_end <= span_start:
        raise ConfirmationContractError("span is outside the source text")
    if quote != source.text[span_start:span_end]:
        raise ConfirmationContractError("quote does not equal source[start:end]")
    if not quote.strip():
        raise ConfirmationContractError("quote must contain visible text")


class AssertionCandidate(_SealedContractModel):
    """模型提出、但由来源区间约束的候选断言。"""

    assertion_id: str = Field(default="", max_length=128)
    source_id: str = Field(min_length=1, max_length=128)
    source_hash: str = Field(pattern=_DIGEST_PATTERN)
    span_start: int = Field(ge=0, le=MAX_SOURCE_CHARS)
    span_end: int = Field(gt=0, le=MAX_SOURCE_CHARS)
    quote: str = Field(min_length=1, max_length=MAX_QUOTE_CHARS)
    domain: RequirementDomain
    meaning: AssertionMeaning
    allowed_decisions: Tuple[AssertionDecision, ...] = Field(
        min_length=1,
        max_length=4,
    )
    object_label: str = Field(min_length=1, max_length=MAX_OBJECT_LABEL_CHARS)
    normalized_object: str = Field(default="", max_length=MAX_OBJECT_LABEL_CHARS)
    execution: Optional[RequirementExecution] = None
    assertion_hash: str = Field(default="", pattern=_DIGEST_PATTERN)

    @model_validator(mode="before")
    @classmethod
    def _seal_assertion(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        values = dict(data)
        source_id = values.get("source_id")
        source_hash = values.get("source_hash")
        object_label = values.get("object_label")
        if (
            not isinstance(source_id, str)
            or not isinstance(source_hash, str)
            or not isinstance(object_label, str)
        ):
            return values
        normalized_object = normalize_object_label(object_label)
        if not normalized_object:
            return values
        allowed_decisions = _normalize_allowed_decisions(
            values.get("allowed_decisions")
        )
        if allowed_decisions is None:
            return values
        core = _assertion_core_payload(
            source_id=source_id,
            source_hash=source_hash,
            span_start=values.get("span_start"),
            span_end=values.get("span_end"),
            quote=values.get("quote"),
            domain=values.get("domain"),
            meaning=values.get("meaning"),
            allowed_decisions=allowed_decisions,
            object_label=object_label,
            normalized_object=normalized_object,
            execution=values.get("execution"),
        )
        digest = _canonical_hash(core)
        assertion_id = f"assertion_{digest[:24]}"
        assertion_hash = _canonical_hash(
            {**core, "assertion_id": assertion_id}
        )
        supplied_id = values.get("assertion_id")
        if supplied_id not in (None, "", assertion_id):
            raise ValueError("assertion_id does not match assertion content")
        supplied_hash = values.get("assertion_hash")
        if supplied_hash not in (None, "", assertion_hash):
            raise ValueError("assertion_hash does not match assertion content")
        supplied_normalized = values.get("normalized_object")
        if supplied_normalized not in (None, "", normalized_object):
            raise ValueError("normalized_object is not deterministic")
        values["assertion_id"] = assertion_id
        values["assertion_hash"] = assertion_hash
        values["allowed_decisions"] = allowed_decisions
        values["normalized_object"] = normalized_object
        return values

    @model_validator(mode="after")
    def _validate_span(self) -> "AssertionCandidate":
        if self.span_end <= self.span_start:
            raise ValueError("span_end must be greater than span_start")
        if not self.quote.strip():
            raise ValueError("quote must contain visible text")
        assert_object_label_bound(self.object_label, self.quote)
        return self


def assert_assertion_integrity(assertion: AssertionCandidate) -> None:
    """复核候选的受控字段和摘要，防止 ``model_copy`` 绕过构造器。"""

    if assertion.normalized_object != normalize_object_label(
        assertion.object_label
    ):
        raise ConfirmationContractError(
            "normalized_object is not deterministic"
        )
    _assert_allowed_decisions(assertion.allowed_decisions)
    core = _assertion_core_payload(
        source_id=assertion.source_id,
        source_hash=assertion.source_hash,
        span_start=assertion.span_start,
        span_end=assertion.span_end,
        quote=assertion.quote,
        domain=assertion.domain,
        meaning=assertion.meaning,
        allowed_decisions=assertion.allowed_decisions,
        object_label=assertion.object_label,
        normalized_object=assertion.normalized_object,
        execution=assertion.execution,
    )
    digest = _canonical_hash(core)
    expected_id = f"assertion_{digest[:24]}"
    expected_hash = _canonical_hash(
        {**core, "assertion_id": expected_id}
    )
    if (
        assertion.assertion_id != expected_id
        or assertion.assertion_hash != expected_hash
    ):
        raise ConfirmationContractError(
            "assertion_hash does not match assertion content"
        )


def build_assertion_candidate(
    *,
    source: SourceEvidence,
    span_start: int,
    span_end: int,
    quote: str,
    domain: RequirementDomain,
    meaning: AssertionMeaning,
    allowed_decisions: Sequence[AssertionDecision],
    object_label: str,
    execution: Optional[RequirementExecution] = None,
) -> AssertionCandidate:
    """从服务端来源构造候选；区间或原文不匹配时直接拒绝。"""

    assert_source_integrity(source)
    assert_quote_span(
        source,
        span_start=span_start,
        span_end=span_end,
        quote=quote,
    )
    assert_object_label_bound(object_label, quote)
    return AssertionCandidate(
        source_id=source.source_id,
        source_hash=source.source_hash,
        span_start=span_start,
        span_end=span_end,
        quote=quote,
        domain=domain,
        meaning=meaning,
        allowed_decisions=allowed_decisions,
        object_label=object_label,
        execution=execution,
    )


class SourceDigest(_SealedContractModel):
    source_id: str = Field(min_length=1, max_length=128)
    source_hash: str = Field(pattern=_DIGEST_PATTERN)


class AssertionDigest(_SealedContractModel):
    assertion_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=128)
    assertion_hash: str = Field(pattern=_DIGEST_PATTERN)


class ConfirmationChallenge(_SealedContractModel):
    """服务端一次待确认集合；token 由内容、身份、策略和修订号共同决定。"""

    run_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=0)
    identity_hash: str = Field(pattern=_DIGEST_PATTERN)
    policy_version: str = Field(min_length=1, max_length=128)
    candidate_contract_hash: str = Field(pattern=_DIGEST_PATTERN)
    source_digests: Tuple[SourceDigest, ...] = Field(
        min_length=1, max_length=MAX_SOURCES
    )
    assertion_digests: Tuple[AssertionDigest, ...] = Field(
        min_length=1, max_length=MAX_ASSERTIONS
    )
    token: str = Field(default="", pattern=_TOKEN_PATTERN)

    @model_validator(mode="before")
    @classmethod
    def _seal_challenge(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        values = dict(data)
        source_rows = _digest_rows(
            values.get("source_digests"),
            model=SourceDigest,
            key="source_id",
        )
        assertion_rows = _digest_rows(
            values.get("assertion_digests"),
            model=AssertionDigest,
            key="assertion_id",
        )
        if source_rows is None or assertion_rows is None:
            return values
        token = _challenge_token(
            run_id=values.get("run_id"),
            session_id=values.get("session_id"),
            revision=values.get("revision"),
            identity_hash=values.get("identity_hash"),
            policy_version=values.get("policy_version"),
            candidate_contract_hash=values.get("candidate_contract_hash"),
            source_rows=source_rows,
            assertion_rows=assertion_rows,
        )
        supplied = values.get("token")
        if supplied not in (None, "", token):
            raise ValueError("challenge token does not match challenge content")
        values["source_digests"] = source_rows
        values["assertion_digests"] = assertion_rows
        values["token"] = token
        return values

    @model_validator(mode="after")
    def _validate_digests(self) -> "ConfirmationChallenge":
        _ensure_unique(
            (item.source_id for item in self.source_digests),
            "duplicate source digest",
        )
        _ensure_unique(
            (item.assertion_id for item in self.assertion_digests),
            "duplicate assertion digest",
        )
        return self


def _digest_rows(
    value: object,
    *,
    model: type[StrictModel],
    key: str,
) -> Optional[Tuple[Dict[str, object], ...]]:
    if not isinstance(value, (list, tuple)):
        return None
    rows: List[Dict[str, object]] = []
    for item in value:
        if isinstance(item, model):
            row = item.model_dump(mode="json")
        elif isinstance(item, dict):
            row = dict(item)
        else:
            return None
        rows.append(row)
    rows.sort(key=lambda row: str(row.get(key, "")))
    return tuple(rows)


def _challenge_token(
    *,
    run_id: object,
    session_id: object,
    revision: object,
    identity_hash: object,
    policy_version: object,
    candidate_contract_hash: object,
    source_rows: Iterable[Dict[str, object]],
    assertion_rows: Iterable[Dict[str, object]],
) -> str:
    payload = {
        "schema_version": CONFIRMATION_CONTRACT_VERSION,
        "run_id": run_id,
        "session_id": session_id,
        "revision": revision,
        "identity_hash": identity_hash,
        "policy_version": policy_version,
        "candidate_contract_hash": candidate_contract_hash,
        "source_digests": list(source_rows),
        "assertion_digests": list(assertion_rows),
    }
    return f"challenge_{_canonical_hash(payload)}"


def _ensure_unique(values: Iterable[str], message: str) -> None:
    seen = set()
    for value in values:
        if value in seen:
            raise ValueError(message)
        seen.add(value)


def _source_digests(sources: Sequence[SourceEvidence]) -> Tuple[SourceDigest, ...]:
    rows = tuple(
        SourceDigest(source_id=source.source_id, source_hash=source.source_hash)
        for source in sources
    )
    _ensure_unique((row.source_id for row in rows), "duplicate source id")
    return tuple(sorted(rows, key=lambda row: row.source_id))


def _assertion_digests(
    assertions: Sequence[AssertionCandidate],
) -> Tuple[AssertionDigest, ...]:
    rows = tuple(
        AssertionDigest(
            assertion_id=assertion.assertion_id,
            source_id=assertion.source_id,
            assertion_hash=assertion.assertion_hash,
        )
        for assertion in assertions
    )
    _ensure_unique(
        (row.assertion_id for row in rows),
        "duplicate assertion id",
    )
    return tuple(sorted(rows, key=lambda row: row.assertion_id))


def build_confirmation_challenge(
    *,
    run_id: str,
    session_id: str,
    revision: int,
    identity_hash: str,
    policy_version: str,
    candidate_contract_hash: str,
    sources: Sequence[SourceEvidence],
    assertions: Sequence[AssertionCandidate],
    previous: Optional[ConfirmationChallenge] = None,
) -> ConfirmationChallenge:
    """创建服务端挑战；修订号必须相对上一版严格递增。"""

    sources = tuple(sources)
    assertions = tuple(assertions)
    if not sources:
        raise ConfirmationContractError("at least one source is required")
    if not assertions:
        raise ConfirmationContractError("at least one assertion is required")
    if len(sources) > MAX_SOURCES:
        raise ConfirmationContractError("too many sources")
    if len(assertions) > MAX_ASSERTIONS:
        raise ConfirmationContractError("too many assertions")

    source_by_id = {source.source_id: source for source in sources}
    if len(source_by_id) != len(sources):
        raise ConfirmationContractError("duplicate source id")
    for source in sources:
        assert_source_integrity(source)
    assertion_ids = {assertion.assertion_id for assertion in assertions}
    if len(assertion_ids) != len(assertions):
        raise ConfirmationContractError("duplicate assertion id")

    for assertion in assertions:
        assert_object_label_bound(assertion.object_label, assertion.quote)
        assert_assertion_integrity(assertion)
        source = source_by_id.get(assertion.source_id)
        if source is None:
            raise ConfirmationContractError("assertion references an unknown source")
        if source.source_hash != assertion.source_hash:
            raise ConfirmationContractError(
                "assertion source revision does not match source evidence"
            )
        assert_quote_span(
            source,
            span_start=assertion.span_start,
            span_end=assertion.span_end,
            quote=assertion.quote,
        )

    if previous is not None:
        if (
            previous.run_id != run_id
            or previous.session_id != session_id
            or previous.identity_hash != identity_hash
            or previous.policy_version != policy_version
        ):
            raise ConfirmationContractError(
                "challenge revision must stay within the same run/session"
            )
        if revision <= previous.revision:
            raise ConfirmationContractError(
                "challenge revision must strictly increase"
            )

    return ConfirmationChallenge(
        run_id=run_id,
        session_id=session_id,
        revision=revision,
        identity_hash=identity_hash,
        policy_version=policy_version,
        candidate_contract_hash=candidate_contract_hash,
        source_digests=_source_digests(sources),
        assertion_digests=_assertion_digests(assertions),
    )


class AssertionDecisionInput(_SealedContractModel):
    """用户提交的最小信息：只允许断言 ID 和显式决定。"""

    assertion_id: str = Field(min_length=1, max_length=128)
    decision: AssertionDecision


class ConfirmationDecisionRecord(_SealedContractModel):
    assertion_id: str = Field(min_length=1, max_length=128)
    assertion_hash: str = Field(pattern=_DIGEST_PATTERN)
    source_id: str = Field(min_length=1, max_length=128)
    source_hash: str = Field(pattern=_DIGEST_PATTERN)
    source_kind: SourceKind
    span_start: int = Field(ge=0, le=MAX_SOURCE_CHARS)
    span_end: int = Field(gt=0, le=MAX_SOURCE_CHARS)
    quote: str = Field(min_length=1, max_length=MAX_QUOTE_CHARS)
    domain: RequirementDomain
    meaning: AssertionMeaning
    allowed_decisions: Tuple[AssertionDecision, ...] = Field(
        min_length=1,
        max_length=4,
    )
    object_label: str = Field(min_length=1, max_length=MAX_OBJECT_LABEL_CHARS)
    normalized_object: str = Field(min_length=1, max_length=MAX_OBJECT_LABEL_CHARS)
    execution: Optional[RequirementExecution] = None
    decision: AssertionDecision

    @model_validator(mode="before")
    @classmethod
    def _normalize_allowed_decisions_field(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        values = dict(data)
        normalized = _normalize_allowed_decisions(
            values.get("allowed_decisions")
        )
        if normalized is not None:
            values["allowed_decisions"] = normalized
        return values

    @model_validator(mode="after")
    def _validate_object_label(self) -> "ConfirmationDecisionRecord":
        assert_object_label_bound(self.object_label, self.quote)
        if self.normalized_object != normalize_object_label(self.object_label):
            raise ValueError("normalized_object is not deterministic")
        return self


def assert_assertion_record_integrity(
    record: ConfirmationDecisionRecord,
) -> None:
    """从 receipt 记录字段重算候选 ID/hash，不能沿用旧摘要换字面对象。"""

    if record.normalized_object != normalize_object_label(record.object_label):
        raise ConfirmationContractError(
            "normalized_object is not deterministic"
        )
    _assert_allowed_decisions(record.allowed_decisions)
    core = _assertion_core_payload(
        source_id=record.source_id,
        source_hash=record.source_hash,
        span_start=record.span_start,
        span_end=record.span_end,
        quote=record.quote,
        domain=record.domain,
        meaning=record.meaning,
        allowed_decisions=record.allowed_decisions,
        object_label=record.object_label,
        normalized_object=record.normalized_object,
        execution=record.execution,
    )
    digest = _canonical_hash(core)
    expected_id = f"assertion_{digest[:24]}"
    expected_hash = _canonical_hash(
        {**core, "assertion_id": expected_id}
    )
    if (
        record.assertion_id != expected_id
        or record.assertion_hash != expected_hash
    ):
        raise ConfirmationContractError(
            "assertion_hash does not match assertion content"
        )


def _decision_record_payload(
    record: ConfirmationDecisionRecord,
) -> Dict[str, object]:
    payload = record.model_dump(mode="json")
    if record.execution is None:
        payload.pop("execution", None)
    return payload


class ConfirmationReceipt(_SealedContractModel):
    """只由服务端挑战和用户显式决定构造的回执。"""

    run_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    challenge_token: str = Field(pattern=_TOKEN_PATTERN)
    challenge_revision: int = Field(ge=0)
    identity_hash: str = Field(pattern=_DIGEST_PATTERN)
    policy_version: str = Field(min_length=1, max_length=128)
    candidate_contract_hash: str = Field(pattern=_DIGEST_PATTERN)
    sources: Tuple[SourceEvidence, ...] = Field(
        min_length=1, max_length=MAX_SOURCES
    )
    decisions: Tuple[ConfirmationDecisionRecord, ...] = Field(
        min_length=1, max_length=MAX_DECISIONS
    )
    included_assertion_ids: Tuple[str, ...] = Field(
        default_factory=tuple, max_length=MAX_ASSERTIONS
    )
    avoided_assertion_ids: Tuple[str, ...] = Field(
        default_factory=tuple, max_length=MAX_ASSERTIONS
    )
    historical_assertion_ids: Tuple[str, ...] = Field(
        default_factory=tuple, max_length=MAX_ASSERTIONS
    )
    unknown_assertion_ids: Tuple[str, ...] = Field(
        default_factory=tuple, max_length=MAX_ASSERTIONS
    )
    incomplete: bool
    # 空串表示让 _seal_receipt 重新计算；hash 只是完整性检查，不是鉴权。
    receipt_hash: str = Field(default="", pattern=_OPTIONAL_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _seal_receipt(self) -> "ConfirmationReceipt":
        groups = (
            self.included_assertion_ids,
            self.avoided_assertion_ids,
            self.historical_assertion_ids,
            self.unknown_assertion_ids,
        )
        all_ids = [value for group in groups for value in group]
        _ensure_unique(all_ids, "decision group overlap")
        _ensure_unique(
            (item.assertion_id for item in self.decisions),
            "duplicate decision record",
        )
        if self.incomplete != bool(self.unknown_assertion_ids):
            raise ValueError("incomplete must exactly reflect unknown decisions")

        decision_groups = {
            AssertionDecision.INCLUDE: self.included_assertion_ids,
            AssertionDecision.AVOID: self.avoided_assertion_ids,
            AssertionDecision.HISTORICAL: self.historical_assertion_ids,
            AssertionDecision.UNKNOWN: self.unknown_assertion_ids,
        }
        for decision, group in decision_groups.items():
            expected_group = tuple(
                item.assertion_id
                for item in self.decisions
                if item.decision is decision
            )
            if tuple(sorted(group)) != tuple(sorted(expected_group)):
                raise ValueError(
                    "decision groups do not match decision records"
                )

        source_by_id = {source.source_id: source for source in self.sources}
        if len(source_by_id) != len(self.sources):
            raise ValueError("duplicate source in receipt")
        for record in self.decisions:
            source = source_by_id.get(record.source_id)
            if source is None:
                raise ValueError(
                    "decision references a source not present in receipt"
                )
            if source.source_hash != record.source_hash:
                raise ValueError(
                    "decision source hash does not match receipt source"
                )
            if source.kind != record.source_kind:
                raise ValueError(
                    "decision source kind does not match receipt source"
                )
            try:
                assert_source_integrity(source)
                assert_quote_span(
                    source,
                    span_start=record.span_start,
                    span_end=record.span_end,
                    quote=record.quote,
                )
                assert_object_label_bound(record.object_label, record.quote)
            except ConfirmationContractError as exc:
                raise ValueError(str(exc)) from exc
            if record.normalized_object != normalize_object_label(
                record.object_label
            ):
                raise ValueError("normalized_object is not deterministic")
            try:
                assert_assertion_record_integrity(record)
            except ConfirmationContractError as exc:
                raise ValueError(str(exc)) from exc

        for record in self.decisions:
            if record.decision not in record.allowed_decisions:
                raise ValueError(
                    "decision is not allowed for this assertion"
                )

        positive_by_key: Dict[str, AssertionDecision] = {}
        for record in self.decisions:
            if record.decision not in {
                AssertionDecision.INCLUDE,
                AssertionDecision.AVOID,
            }:
                continue
            source = source_by_id[record.source_id]
            if source.kind in NON_AUTHORIZING_SOURCE_KINDS:
                raise ValueError(
                    "saved preference or trip context must be re-entered "
                    "explicitly"
                )
            if (
                source.kind is SourceKind.EXPLICIT_SELECTION
                and not _has_independent_selection_evidence(
                    record.object_label,
                    self.sources,
                )
            ):
                raise ValueError(
                    "explicit selection requires independent text evidence"
                )
            # 该原语还没有可验证的适用人和作用域；相同归一化对象即使落在
            # 不同 domain，也保守阻断 include/avoid 冲突。
            key = record.normalized_object
            prior = positive_by_key.get(key)
            if prior is not None and prior is not record.decision:
                raise ValueError(
                    "include and avoid conflict on the same normalized object"
                )
            positive_by_key[key] = record.decision

        source_digests = _source_digests(self.sources)
        assertion_digests = tuple(
            AssertionDigest(
                assertion_id=record.assertion_id,
                source_id=record.source_id,
                assertion_hash=record.assertion_hash,
            )
            for record in self.decisions
        )
        _ensure_unique(
            (row.assertion_id for row in assertion_digests),
            "duplicate assertion digest",
        )
        assertion_digests = tuple(
            sorted(assertion_digests, key=lambda row: row.assertion_id)
        )
        expected_token = _challenge_token(
            run_id=self.run_id,
            session_id=self.session_id,
            revision=self.challenge_revision,
            identity_hash=self.identity_hash,
            policy_version=self.policy_version,
            candidate_contract_hash=self.candidate_contract_hash,
            source_rows=[
                row.model_dump(mode="json") for row in source_digests
            ],
            assertion_rows=[
                row.model_dump(mode="json") for row in assertion_digests
            ],
        )
        if expected_token != self.challenge_token:
            raise ValueError(
                "challenge_token does not match receipt content"
            )

        expected = _canonical_hash(
            {
                "schema_version": CONFIRMATION_CONTRACT_VERSION,
                "run_id": self.run_id,
                "session_id": self.session_id,
                "challenge_token": self.challenge_token,
                "challenge_revision": self.challenge_revision,
                "identity_hash": self.identity_hash,
                "policy_version": self.policy_version,
                "candidate_contract_hash": self.candidate_contract_hash,
                "sources": [
                    source.model_dump(mode="json") for source in self.sources
                ],
                "decisions": [
                    _decision_record_payload(record)
                    for record in self.decisions
                ],
                "included_assertion_ids": list(self.included_assertion_ids),
                "avoided_assertion_ids": list(self.avoided_assertion_ids),
                "historical_assertion_ids": list(
                    self.historical_assertion_ids
                ),
                "unknown_assertion_ids": list(self.unknown_assertion_ids),
                "incomplete": self.incomplete,
            }
        )
        if self.receipt_hash and self.receipt_hash != expected:
            raise ValueError("receipt_hash does not match receipt content")
        object.__setattr__(self, "receipt_hash", expected)
        return self


def _challenge_digest_mismatch(
    *,
    challenge: ConfirmationChallenge,
    sources: Sequence[SourceEvidence],
    assertions: Sequence[AssertionCandidate],
) -> bool:
    source_digests = _source_digests(sources)
    assertion_digests = _assertion_digests(assertions)
    return (
        tuple(source_digests) != tuple(challenge.source_digests)
        or tuple(assertion_digests) != tuple(challenge.assertion_digests)
    )


def build_confirmation_receipt(
    *,
    challenge: ConfirmationChallenge,
    sources: Sequence[SourceEvidence],
    assertions: Sequence[AssertionCandidate],
    decisions: Sequence[AssertionDecisionInput],
    submitted_token: str,
    run_id: str,
    session_id: str,
    identity_hash: str,
    policy_version: str,
) -> ConfirmationReceipt:
    """用服务端挑战 + 用户 ID/决定生成回执。

    调用方不能提交文本、标签或正向集合；这些只能来自挑战对应的服务端候选。
    """

    if submitted_token != challenge.token:
        raise ConfirmationRejected("stale challenge token")
    if run_id != challenge.run_id:
        raise ConfirmationRejected("receipt is bound to a different run")
    if session_id != challenge.session_id:
        raise ConfirmationRejected("receipt is bound to a different session")
    if identity_hash != challenge.identity_hash:
        raise ConfirmationRejected("receipt identity hash does not match")
    if policy_version != challenge.policy_version:
        raise ConfirmationRejected("receipt policy version does not match")

    sources = tuple(sources)
    assertions = tuple(assertions)
    decisions = tuple(decisions)
    if not decisions:
        raise ConfirmationRejected("every assertion requires an explicit decision")
    if len(decisions) > MAX_DECISIONS:
        raise ConfirmationRejected("too many decisions")
    for source in sources:
        try:
            assert_source_integrity(source)
        except ConfirmationContractError as exc:
            raise ConfirmationRejected(str(exc)) from exc

    try:
        digest_mismatch = _challenge_digest_mismatch(
            challenge=challenge,
            sources=sources,
            assertions=assertions,
        )
    except ValueError as exc:
        raise ConfirmationRejected(str(exc)) from exc
    if digest_mismatch:
        raise ConfirmationRejected("server challenge digests do not match")

    source_by_id = {source.source_id: source for source in sources}
    assertion_by_id = {
        assertion.assertion_id: assertion for assertion in assertions
    }
    if len(assertion_by_id) != len(assertions):
        raise ConfirmationRejected("duplicate server assertion")
    for assertion in assertions:
        try:
            assert_object_label_bound(assertion.object_label, assertion.quote)
            assert_assertion_integrity(assertion)
        except ConfirmationContractError as exc:
            raise ConfirmationRejected(str(exc)) from exc
        source = source_by_id.get(assertion.source_id)
        if source is None:
            raise ConfirmationRejected("assertion references an unknown source")
        if source.source_hash != assertion.source_hash:
            raise ConfirmationRejected(
                "assertion source revision does not match source evidence"
            )
        try:
            assert_quote_span(
                source,
                span_start=assertion.span_start,
                span_end=assertion.span_end,
                quote=assertion.quote,
            )
            assert_object_label_bound(assertion.object_label, assertion.quote)
        except ConfirmationContractError as exc:
            raise ConfirmationRejected(str(exc)) from exc

    decision_by_id: Dict[str, AssertionDecision] = {}
    for decision in decisions:
        if decision.assertion_id in decision_by_id:
            raise ConfirmationRejected("duplicate assertion decision")
        decision_by_id[decision.assertion_id] = decision.decision

    expected_ids = set(assertion_by_id)
    submitted_ids = set(decision_by_id)
    if submitted_ids - expected_ids:
        raise ConfirmationRejected("decision references an unknown assertion")
    if expected_ids - submitted_ids:
        raise ConfirmationRejected("decision is missing an assertion")

    for assertion_id, decision in decision_by_id.items():
        assertion = assertion_by_id[assertion_id]
        if decision not in assertion.allowed_decisions:
            raise ConfirmationRejected(
                "decision is not allowed for this assertion"
            )

    # 先检查非授权来源，避免它们进入任何正向集合。
    for assertion_id, decision in decision_by_id.items():
        if decision not in {AssertionDecision.INCLUDE, AssertionDecision.AVOID}:
            continue
        assertion = assertion_by_id[assertion_id]
        source = source_by_id.get(assertion.source_id)
        if source is None:
            raise ConfirmationRejected("assertion references an unknown source")
        if source.kind in NON_AUTHORIZING_SOURCE_KINDS:
            raise ConfirmationRejected(
                "saved preference or trip context must be re-entered explicitly"
            )
        if (
            source.kind is SourceKind.EXPLICIT_SELECTION
            and not _has_independent_selection_evidence(
                assertion.object_label,
                sources,
            )
        ):
            raise ConfirmationRejected(
                "explicit selection requires independent text evidence"
            )

    # 该原语还没有可验证的适用人和作用域；相同归一化对象即使落在不同
    # domain，也保守阻断 include/avoid 冲突。
    positive_by_key: Dict[str, AssertionDecision] = {}
    for assertion_id, decision in decision_by_id.items():
        if decision not in {AssertionDecision.INCLUDE, AssertionDecision.AVOID}:
            continue
        assertion = assertion_by_id[assertion_id]
        key = assertion.normalized_object
        prior = positive_by_key.get(key)
        if prior is not None and prior is not decision:
            raise ConfirmationRejected(
                "include and avoid conflict on the same normalized object"
            )
        positive_by_key[key] = decision

    records: List[ConfirmationDecisionRecord] = []
    for assertion_id in sorted(assertion_by_id):
        assertion = assertion_by_id[assertion_id]
        source = source_by_id.get(assertion.source_id)
        if source is None:
            raise ConfirmationRejected("assertion references an unknown source")
        records.append(
            ConfirmationDecisionRecord(
                assertion_id=assertion.assertion_id,
                assertion_hash=assertion.assertion_hash,
                source_id=source.source_id,
                source_hash=source.source_hash,
                source_kind=source.kind,
                span_start=assertion.span_start,
                span_end=assertion.span_end,
                quote=assertion.quote,
                domain=assertion.domain,
                meaning=assertion.meaning,
                allowed_decisions=assertion.allowed_decisions,
                object_label=assertion.object_label,
                normalized_object=assertion.normalized_object,
                execution=assertion.execution,
                decision=decision_by_id[assertion_id],
            )
        )

    def ids_for(decision: AssertionDecision) -> Tuple[str, ...]:
        return tuple(
            record.assertion_id
            for record in records
            if record.decision is decision
        )

    unknown_ids = ids_for(AssertionDecision.UNKNOWN)
    return ConfirmationReceipt(
        run_id=challenge.run_id,
        session_id=challenge.session_id,
        challenge_token=challenge.token,
        challenge_revision=challenge.revision,
        identity_hash=challenge.identity_hash,
        policy_version=challenge.policy_version,
        candidate_contract_hash=challenge.candidate_contract_hash,
        sources=tuple(sorted(sources, key=lambda source: source.source_id)),
        decisions=tuple(records),
        included_assertion_ids=ids_for(AssertionDecision.INCLUDE),
        avoided_assertion_ids=ids_for(AssertionDecision.AVOID),
        historical_assertion_ids=ids_for(AssertionDecision.HISTORICAL),
        unknown_assertion_ids=unknown_ids,
        incomplete=bool(unknown_ids),
    )
