"""Server-owned, bounded candidate selection for research plans.

This module is intentionally standalone: it does not build a plan, call providers,
or fall back to model-authored names. The caller must construct
:class:`CandidateSelectionInput` only after it has obtained an explicit semantic
confirmation from the user. The server-stored ``confirmation_digest`` is carried
through unchanged; this module does not verify the confirmation itself.

The authorized candidate list is server-owned, but it is still treated as
untrusted at the parsing boundary together with the model response. Validation
here constrains the selection contract; it is not by itself a safety guarantee.
"""

from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from collections import Counter
from enum import Enum
from typing import Annotated
from typing import Dict
from typing import List
from typing import Mapping
from typing import Optional
from typing import Protocol
from typing import Sequence
from typing import Tuple

from pydantic import Field
from pydantic import ValidationError
from pydantic import model_validator

from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.schema import StrictModel

SELECTION_SCHEMA_VERSION = "journeypilot.research_selection.v1"

MAX_REQUIRED_DOMAINS = len(ResearchDomain)
MAX_CANDIDATES_PER_DOMAIN = 12
MAX_TOTAL_CANDIDATES = 40
MAX_CANDIDATE_ID_LENGTH = 64
MAX_CANDIDATE_LABEL_LENGTH = 120
MAX_SELECTED_CANDIDATES_PER_KIND = 5
MAX_PROMPT_CHARS = 16_000
MAX_MODEL_RESPONSE_CHARS = 16_000
DEFAULT_SELECTION_TIMEOUT_SECONDS = 30.0
MAX_SELECTION_TIMEOUT_SECONDS = 120.0

_CANDIDATE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
_CONFIRMATION_DIGEST_PATTERN = r"^[0-9a-f]{64}$"
_INTERNAL_LABEL_PATTERN = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+(?![A-Za-z0-9_])")
_INTERNAL_LABEL_NAMES = frozenset(
    {
        *(domain.value for domain in ResearchDomain),
        "candidate",
        "none",
        "null",
        "placeholder",
        "unknown",
        "unnamed",
    }
)
_DOMAIN_ORDER = {domain: index for index, domain in enumerate(ResearchDomain)}

_SYSTEM_PROMPT = (
    "Select from the server-authorized research candidates below. Return exactly "
    "one JSON object, with no Markdown, commentary, names, terms, or extra fields. "
    "Only use candidate_id values supplied below, and only under their own domain. "
    "Every required domain must appear exactly once. Each domain must contain at "
    "least one focus_candidate_ids entry and one search_candidate_ids entry. "
    "An ID may not repeat inside either list, though the same ID may appear "
    "in both focus_candidate_ids and search_candidate_ids. "
    'Required shape: {"domains": {"<domain>": {"focus_candidate_ids": ["id"], '
    '"search_candidate_ids": ["id"]}}}. '
    f"At most {MAX_SELECTED_CANDIDATES_PER_KIND} IDs are allowed in each list."
)


class CandidateSelectionStatus(str, Enum):
    SELECTED = "selected"
    FAILED = "failed"


class CandidateSelectionFailureCode(str, Enum):
    MODEL_TIMEOUT = "model_timeout"
    MODEL_PROVIDER_FAILURE = "model_provider_failure"
    MODEL_OUTPUT_INVALID = "model_output_invalid"


class AuthorizedCandidate(StrictModel):
    """A server-authorized candidate with a stable opaque ID and bounded label.

    ``label`` is the server-owned display/search label. It never comes from the
    model response.
    """

    candidate_id: str = Field(
        min_length=1,
        max_length=MAX_CANDIDATE_ID_LENGTH,
        pattern=_CANDIDATE_ID_PATTERN,
    )
    domain: ResearchDomain
    label: str = Field(min_length=1, max_length=MAX_CANDIDATE_LABEL_LENGTH)

    @model_validator(mode="after")
    def validate_label(self) -> "AuthorizedCandidate":
        if self.label != self.label.strip():
            raise ValueError("candidate label must not have surrounding whitespace")
        if not self.label.strip():
            raise ValueError("candidate label must not be blank")
        if any(unicodedata.category(character).startswith("C") for character in self.label):
            raise ValueError("candidate label must not contain control or format characters")
        folded = self.label.casefold()
        if folded == self.candidate_id.casefold():
            raise ValueError("candidate label must not be the opaque candidate id")
        if folded in _INTERNAL_LABEL_NAMES:
            raise ValueError("candidate label must not be an internal name")
        if _INTERNAL_LABEL_PATTERN.search(self.label):
            raise ValueError("candidate label must not be an internal identifier")
        return self


class CandidateSelectionInput(StrictModel):
    """Frozen server input for one explicit, user-confirmed selection request.

    Construct this only after necessary requirement clarification. ``candidates`` is
    the complete authorized set for the required domains; candidate IDs and
    labels must already be server-owned and bounded. The caller supplies the
    server-stored confirmation digest.
    """

    schema_version: str = Field(
        default=SELECTION_SCHEMA_VERSION,
        pattern=f"^{re.escape(SELECTION_SCHEMA_VERSION)}$",
    )
    confirmation_digest: str = Field(pattern=_CONFIRMATION_DIGEST_PATTERN)
    required_domains: frozenset[ResearchDomain] = Field(
        min_length=1,
        max_length=MAX_REQUIRED_DOMAINS,
    )
    candidates: frozenset[AuthorizedCandidate] = Field(
        min_length=1,
        max_length=MAX_TOTAL_CANDIDATES,
    )

    @model_validator(mode="after")
    def validate_candidate_set(self) -> "CandidateSelectionInput":
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("authorized candidate ids must be globally unique")
        candidate_domains = {candidate.domain for candidate in self.candidates}
        if candidate_domains != set(self.required_domains):
            raise ValueError(
                "authorized candidate domains must exactly match required domains"
            )

        per_domain = Counter(candidate.domain for candidate in self.candidates)
        if any(
            count > MAX_CANDIDATES_PER_DOMAIN for count in per_domain.values()
        ):
            raise ValueError("too many authorized candidates in one domain")

        labels_by_domain: Dict[ResearchDomain, set[str]] = {
            domain: set() for domain in self.required_domains
        }
        for candidate in self.candidates:
            label_key = " ".join(candidate.label.split()).casefold()
            if label_key in labels_by_domain[candidate.domain]:
                raise ValueError(
                    "authorized candidate labels must be unique within a domain"
                )
            labels_by_domain[candidate.domain].add(label_key)
        return self


class SelectionModel(Protocol):
    async def ainvoke(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        response_format: Optional[Mapping[str, str]] = None,
    ) -> object: ...


class DomainLabelProjection(StrictModel):
    focus_candidate_ids: Tuple[str, ...] = Field(min_length=1, max_length=MAX_SELECTED_CANDIDATES_PER_KIND)
    search_candidate_ids: Tuple[str, ...] = Field(min_length=1, max_length=MAX_SELECTED_CANDIDATES_PER_KIND)
    focus_labels: Tuple[str, ...] = Field(min_length=1, max_length=MAX_SELECTED_CANDIDATES_PER_KIND)
    search_labels: Tuple[str, ...] = Field(min_length=1, max_length=MAX_SELECTED_CANDIDATES_PER_KIND)

    @model_validator(mode="after")
    def validate_lengths(self) -> "DomainLabelProjection":
        if len(self.focus_candidate_ids) != len(self.focus_labels) or len(self.search_candidate_ids) != len(self.search_labels):
            raise ValueError("candidate ids and labels must align")
        return self


class CandidateSelectionFailure(StrictModel):
    code: CandidateSelectionFailureCode
    detail: str = Field(min_length=1, max_length=200)


class CandidateSelectionResult(StrictModel):
    schema_version: str = Field(
        default=SELECTION_SCHEMA_VERSION,
        pattern=f"^{re.escape(SELECTION_SCHEMA_VERSION)}$",
    )
    status: CandidateSelectionStatus
    confirmation_digest: str = Field(pattern=_CONFIRMATION_DIGEST_PATTERN)
    projection: Optional[Dict[str, DomainLabelProjection]] = None
    failure: Optional[CandidateSelectionFailure] = None

    @model_validator(mode="after")
    def validate_result_shape(self) -> "CandidateSelectionResult":
        if self.status is CandidateSelectionStatus.SELECTED:
            if not self.projection or self.failure is not None:
                raise ValueError(
                    "selected result requires a projection and no failure"
                )
        elif self.projection is not None or self.failure is None:
            raise ValueError("failed result requires a failure and no projection")
        return self

    def projection_payload(self) -> Optional[Dict[str, Dict[str, List[str]]]]:
        """Return the plain, deterministic domain -> owned-label projection."""
        if self.projection is None:
            return None
        return {
            domain: {
                "focus_labels": list(terms.focus_labels),
                "search_labels": list(terms.search_labels),
            }
            for domain, terms in self.projection.items()
        }

    def canonical_json(self) -> str:
        """Serialize this result byte-for-byte deterministically."""
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


class _ModelDomainSelection(StrictModel):
    focus_candidate_ids: Tuple[
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=MAX_CANDIDATE_ID_LENGTH,
                pattern=_CANDIDATE_ID_PATTERN,
            ),
        ],
        ...,
    ] = Field(min_length=1, max_length=MAX_SELECTED_CANDIDATES_PER_KIND)
    search_candidate_ids: Tuple[
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=MAX_CANDIDATE_ID_LENGTH,
                pattern=_CANDIDATE_ID_PATTERN,
            ),
        ],
        ...,
    ] = Field(min_length=1, max_length=MAX_SELECTED_CANDIDATES_PER_KIND)


class _ModelSelectionPayload(StrictModel):
    domains: Dict[str, _ModelDomainSelection] = Field(
        min_length=1,
        max_length=MAX_REQUIRED_DOMAINS,
    )


def _validate_timeout(timeout_seconds: float) -> None:
    if isinstance(timeout_seconds, bool) or not isinstance(
        timeout_seconds, (int, float)
    ):
        raise ValueError("selection timeout must be a number")
    if not 0 < timeout_seconds <= MAX_SELECTION_TIMEOUT_SECONDS:
        raise ValueError(
            f"selection timeout must be in (0, {MAX_SELECTION_TIMEOUT_SECONDS}]"
        )


def _canonical_candidates(
    selection_input: CandidateSelectionInput,
) -> List[AuthorizedCandidate]:
    return sorted(
        selection_input.candidates,
        key=lambda candidate: (
            _DOMAIN_ORDER[candidate.domain],
            candidate.candidate_id,
        ),
    )


def _canonical_domains(
    selection_input: CandidateSelectionInput,
) -> List[ResearchDomain]:
    return sorted(selection_input.required_domains, key=_DOMAIN_ORDER.__getitem__)


def build_selection_messages(
    selection_input: CandidateSelectionInput,
) -> Tuple[Dict[str, str], ...]:
    """Build bounded model messages using only server-owned IDs and labels."""
    candidates = _canonical_candidates(selection_input)
    payload = {
        "required_domains": [
            domain.value for domain in _canonical_domains(selection_input)
        ],
        "candidates": [
            {
                "candidate_id": candidate.candidate_id,
                "domain": candidate.domain.value,
                "label": candidate.label,
            }
            for candidate in candidates
        ],
    }
    user_content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    messages = (
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    )
    if sum(len(message["content"]) for message in messages) > MAX_PROMPT_CHARS:
        raise ValueError("selection prompt exceeds the prompt size cap")
    return messages


def _failure(
    selection_input: CandidateSelectionInput,
    code: CandidateSelectionFailureCode,
    detail: str,
) -> CandidateSelectionResult:
    return CandidateSelectionResult(
        status=CandidateSelectionStatus.FAILED,
        confirmation_digest=selection_input.confirmation_digest,
        failure=CandidateSelectionFailure(code=code, detail=detail),
    )


def _invalid_output(
    selection_input: CandidateSelectionInput,
) -> CandidateSelectionResult:
    # Never echo model-provided text or candidate data in a failure result.
    return _failure(
        selection_input,
        CandidateSelectionFailureCode.MODEL_OUTPUT_INVALID,
        "model output did not match the bounded selection contract",
    )


def _reject_duplicate_json_keys(
    pairs: List[Tuple[str, object]],
) -> Dict[str, object]:
    """Build one JSON object while rejecting duplicate keys at every depth."""
    result: Dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("model output contains duplicate JSON keys")
        result[key] = value
    return result


def _parse_model_output(
    raw: object,
    selection_input: CandidateSelectionInput,
) -> Dict[str, DomainLabelProjection]:
    if not isinstance(raw, str):
        raise ValueError("model output must be a JSON string")
    if len(raw) > MAX_MODEL_RESPONSE_CHARS:
        raise ValueError("model output exceeds the response size cap")
    try:
        decoded = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("model output is not exact JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("model output must be one JSON object")
    try:
        model_selection = _ModelSelectionPayload.model_validate(decoded)
    except ValidationError as exc:
        raise ValueError("model output does not match the schema") from exc

    expected_domains = {
        domain.value for domain in selection_input.required_domains
    }
    if set(model_selection.domains) != expected_domains:
        raise ValueError("model output has missing or extra domains")

    candidates_by_domain: Dict[
        ResearchDomain, Dict[str, AuthorizedCandidate]
    ] = {domain: {} for domain in selection_input.required_domains}
    for candidate in selection_input.candidates:
        candidates_by_domain[candidate.domain][candidate.candidate_id] = candidate

    projection: Dict[str, DomainLabelProjection] = {}
    for domain in _canonical_domains(selection_input):
        selected = model_selection.domains[domain.value]
        focus_ids = list(selected.focus_candidate_ids)
        search_ids = list(selected.search_candidate_ids)
        if len(focus_ids) != len(set(focus_ids)) or len(search_ids) != len(
            set(search_ids)
        ):
            raise ValueError(
                "model output contains duplicate candidate ids within a list"
            )

        allowed = candidates_by_domain[domain]
        focus_candidates = []
        for candidate_id in focus_ids:
            candidate = allowed.get(candidate_id)
            if candidate is None:
                raise ValueError("model output contains an unknown candidate id")
            focus_candidates.append(candidate)
        search_candidates = []
        for candidate_id in search_ids:
            candidate = allowed.get(candidate_id)
            if candidate is None:
                raise ValueError("model output contains an unknown candidate id")
            search_candidates.append(candidate)

        focus_candidates.sort(key=lambda candidate: candidate.candidate_id)
        search_candidates.sort(key=lambda candidate: candidate.candidate_id)
        projection[domain.value] = DomainLabelProjection(
            focus_candidate_ids=tuple(candidate.candidate_id for candidate in focus_candidates),
            search_candidate_ids=tuple(candidate.candidate_id for candidate in search_candidates),
            focus_labels=tuple(
                candidate.label for candidate in focus_candidates
            ),
            search_labels=tuple(
                candidate.label for candidate in search_candidates
            ),
        )
    return projection


async def select_research_candidates(
    selection_input: CandidateSelectionInput,
    model: SelectionModel,
    *,
    timeout_seconds: float = DEFAULT_SELECTION_TIMEOUT_SECONDS,
) -> CandidateSelectionResult:
    """Invoke the model exactly once and project selected IDs to owned labels.

    The caller must have already obtained necessary requirement clarification and
    constructed ``selection_input`` from the server-authorized candidate set.
    There are no retries and no fallback selection: a provider failure or timeout
    produces an explicit failed result with no projection. Model output is parsed
    strictly as JSON and checked against the authorized candidates.
    """
    _validate_timeout(timeout_seconds)
    messages = build_selection_messages(selection_input)
    try:
        raw = await asyncio.wait_for(
            model.ainvoke(
                messages,
                response_format={"type": "json_object"},
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        return _failure(
            selection_input,
            CandidateSelectionFailureCode.MODEL_TIMEOUT,
            "model selection exceeded the bounded wait",
        )
    except Exception:
        return _failure(
            selection_input,
            CandidateSelectionFailureCode.MODEL_PROVIDER_FAILURE,
            "model selection provider call failed",
        )

    try:
        projection = _parse_model_output(raw, selection_input)
    except (TypeError, ValueError, ValidationError):
        return _invalid_output(selection_input)

    return CandidateSelectionResult(
        status=CandidateSelectionStatus.SELECTED,
        confirmation_digest=selection_input.confirmation_digest,
        projection=projection,
    )
