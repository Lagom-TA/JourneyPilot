"""Offline contract tests for the server-owned candidate selection primitive."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence
from typing import Tuple

import pytest
from pydantic import ValidationError

from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.selection import (
    DEFAULT_SELECTION_TIMEOUT_SECONDS,
    MAX_CANDIDATE_ID_LENGTH,
    MAX_CANDIDATE_LABEL_LENGTH,
    MAX_CANDIDATES_PER_DOMAIN,
    MAX_PROMPT_CHARS,
    MAX_SELECTED_CANDIDATES_PER_KIND,
    MAX_SELECTION_TIMEOUT_SECONDS,
    MAX_TOTAL_CANDIDATES,
    AuthorizedCandidate,
    CandidateSelectionFailureCode,
    CandidateSelectionInput,
    CandidateSelectionStatus,
    build_selection_messages,
    select_research_candidates,
)

_DIGEST = "a" * 64
_DOMAINS = (ResearchDomain.VISIT, ResearchDomain.DINING)
_CANDIDATES = (
    AuthorizedCandidate(
        candidate_id="v1", domain=ResearchDomain.VISIT, label="City Museum"
    ),
    AuthorizedCandidate(
        candidate_id="v2", domain=ResearchDomain.VISIT, label="River Walk"
    ),
    AuthorizedCandidate(
        candidate_id="v3", domain=ResearchDomain.VISIT, label="Old Town"
    ),
    AuthorizedCandidate(
        candidate_id="d1", domain=ResearchDomain.DINING, label="Noodle Shop"
    ),
    AuthorizedCandidate(
        candidate_id="d2", domain=ResearchDomain.DINING, label="Tea House"
    ),
    AuthorizedCandidate(
        candidate_id="d3", domain=ResearchDomain.DINING, label="Night Market"
    ),
)


def _input(
    candidates: Sequence[AuthorizedCandidate] = _CANDIDATES,
    domains: Sequence[ResearchDomain] = _DOMAINS,
) -> CandidateSelectionInput:
    return CandidateSelectionInput(
        confirmation_digest=_DIGEST,
        required_domains=frozenset(domains),
        candidates=frozenset(candidates),
    )


def _response(
    selections: Dict[str, Tuple[List[str], List[str]]],
    *,
    extra: Optional[Dict[str, object]] = None,
) -> str:
    payload = {
        "domains": {
            domain: {
                "focus_candidate_ids": focus_ids,
                "search_candidate_ids": search_ids,
            }
            for domain, (focus_ids, search_ids) in selections.items()
        }
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload)


def _valid_variant_a() -> str:
    return _response(
        {
            "visit": (["v1"], ["v2"]),
            "dining": (["d1"], ["d3"]),
        }
    )


def _valid_variant_b() -> str:
    return _response(
        {
            "visit": (["v3", "v2"], ["v1"]),
            "dining": (["d3"], ["d1", "d2"]),
        }
    )


class FakeModel:
    def __init__(self, raw: object = None, error: Optional[Exception] = None):
        self.raw = raw
        self.error = error
        self.calls = 0
        self.messages: Sequence[object] = ()

    async def ainvoke(self, messages, *, response_format=None):
        self.calls += 1
        self.messages = messages
        assert response_format == {"type": "json_object"}
        if self.error is not None:
            raise self.error
        return self.raw


class SleepingModel:
    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, messages, *, response_format=None):
        self.calls += 1
        await asyncio.sleep(60)
        return _valid_variant_a()


async def test_two_legal_model_variants_project_only_server_owned_labels() -> None:
    model_a = FakeModel(_valid_variant_a())
    result_a = await select_research_candidates(_input(), model_a)

    model_b = FakeModel(_valid_variant_b())
    result_b = await select_research_candidates(_input(), model_b)

    assert model_a.calls == model_b.calls == 1
    assert result_a.status is CandidateSelectionStatus.SELECTED
    assert result_b.status is CandidateSelectionStatus.SELECTED
    assert result_a.failure is None and result_b.failure is None
    assert result_a.projection_payload() == {
        "visit": {
            "focus_labels": ["City Museum"],
            "search_labels": ["River Walk"],
        },
        "dining": {
            "focus_labels": ["Noodle Shop"],
            "search_labels": ["Night Market"],
        },
    }
    assert result_b.projection_payload() == {
        "visit": {
            "focus_labels": ["River Walk", "Old Town"],
            "search_labels": ["City Museum"],
        },
        "dining": {
            "focus_labels": ["Night Market"],
            "search_labels": ["Noodle Shop", "Tea House"],
        },
    }
    assert result_a.canonical_json() != result_b.canonical_json()
    assert result_a.confirmation_digest == _DIGEST
    assert result_b.confirmation_digest == _DIGEST


async def test_repeated_selection_is_byte_for_byte_deterministic() -> None:
    reordered_variant = _response(
        {
            "dining": (["d1", "d3"], ["d2"]),
            "visit": (["v2", "v3"], ["v1"]),
        }
    )
    same_ids_reordered = _response(
        {
            "visit": (["v3", "v2"], ["v1"]),
            "dining": (["d3", "d1"], ["d2"]),
        }
    )

    first_model = FakeModel(reordered_variant)
    first = await select_research_candidates(_input(), first_model)
    second_model = FakeModel(same_ids_reordered)
    second = await select_research_candidates(_input(), second_model)

    assert first.status is CandidateSelectionStatus.SELECTED
    assert second.status is CandidateSelectionStatus.SELECTED
    assert first_model.calls == second_model.calls == 1
    assert first.canonical_json() == second.canonical_json()
    assert first.projection_payload() == second.projection_payload()
    assert first.projection_payload() == {
        "visit": {
            "focus_labels": ["River Walk", "Old Town"],
            "search_labels": ["City Museum"],
        },
        "dining": {
            "focus_labels": ["Noodle Shop", "Night Market"],
            "search_labels": ["Tea House"],
        },
    }


async def test_phantom_candidate_id_is_an_explicit_invalid_output_failure() -> None:
    model = FakeModel(
        _response(
            {
                "visit": (["v1", "v999"], ["v2"]),
                "dining": (["d1"], ["d3"]),
            }
        )
    )

    result = await select_research_candidates(_input(), model)

    assert model.calls == 1
    assert result.status is CandidateSelectionStatus.FAILED
    assert result.projection is None
    assert result.failure is not None
    assert result.failure.code is CandidateSelectionFailureCode.MODEL_OUTPUT_INVALID
    assert "v999" not in result.canonical_json()


async def test_cross_domain_candidate_id_is_rejected() -> None:
    model = FakeModel(
        _response(
            {
                "visit": (["d1"], ["v2"]),
                "dining": (["d1"], ["d3"]),
            }
        )
    )

    result = await select_research_candidates(_input(), model)

    assert model.calls == 1
    assert result.status is CandidateSelectionStatus.FAILED
    assert result.failure is not None
    assert result.failure.code is CandidateSelectionFailureCode.MODEL_OUTPUT_INVALID


@pytest.mark.parametrize(
    "raw",
    [
        _response({"visit": (["v1"], ["v2"])}),
        _response(
            {
                "visit": (["v1"], ["v2"]),
                "dining": (["d1"], ["d3"]),
                "lodging": (["v1"], ["v1"]),
            }
        ),
        _response(
            {
                "visit": (["v1"], ["v2"]),
                "dining": ([], ["d3"]),
            }
        ),
        json.dumps(
            {
                "domains": {
                    "visit": {
                        "focus_candidate_ids": ["v1"],
                        "search_candidate_ids": ["v2"],
                    },
                    "dining": {"focus_candidate_ids": ["d1"]},
                }
            }
        ),
        "",
        "not json",
    ],
)
async def test_incomplete_missing_or_extra_domain_output_is_rejected(raw: str) -> None:
    model = FakeModel(raw)

    result = await select_research_candidates(_input(), model)

    assert model.calls == 1
    assert result.status is CandidateSelectionStatus.FAILED
    assert result.projection is None
    assert result.failure is not None
    assert result.failure.code is CandidateSelectionFailureCode.MODEL_OUTPUT_INVALID


@pytest.mark.parametrize(
    "raw",
    [
        _response(
            {
                "visit": (["v1"], ["v2"]),
                "dining": (["d1"], ["d3"]),
            },
            extra={"free_text_terms": ["model-authored noodles"]},
        ),
        json.dumps(
            {
                "domains": {
                    "visit": {
                        "focus_candidate_ids": ["v1"],
                        "search_candidate_ids": ["v2"],
                        "display_names": ["model-authored museum"],
                    },
                    "dining": {
                        "focus_candidate_ids": ["d1"],
                        "search_candidate_ids": ["d3"],
                    },
                }
            }
        ),
    ],
)
async def test_malicious_extra_free_text_is_rejected_without_echo(raw: str) -> None:
    model = FakeModel(raw)

    result = await select_research_candidates(_input(), model)

    assert model.calls == 1
    assert result.status is CandidateSelectionStatus.FAILED
    assert result.failure is not None
    assert result.failure.code is CandidateSelectionFailureCode.MODEL_OUTPUT_INVALID
    rendered = result.canonical_json()
    assert "model-authored" not in rendered
    assert "free_text_terms" not in rendered


async def test_single_candidate_may_be_both_focus_and_search() -> None:
    only_candidate = AuthorizedCandidate(
        candidate_id="only",
        domain=ResearchDomain.VISIT,
        label="Only Museum",
    )
    model = FakeModel(
        _response(
            {
                "visit": (["only"], ["only"]),
            }
        )
    )

    result = await select_research_candidates(
        _input((only_candidate,), (ResearchDomain.VISIT,)),
        model,
    )

    assert model.calls == 1
    assert result.status is CandidateSelectionStatus.SELECTED
    assert result.failure is None
    assert result.projection_payload() == {
        "visit": {
            "focus_labels": ["Only Museum"],
            "search_labels": ["Only Museum"],
        },
    }


@pytest.mark.parametrize(
    "selections",
    [
        {
            "visit": (["v1", "v1"], ["v2"]),
            "dining": (["d1"], ["d3"]),
        },
        {
            "visit": (["v1"], ["v2", "v2"]),
            "dining": (["d1"], ["d3"]),
        },
    ],
)
async def test_duplicate_candidate_id_within_one_list_is_rejected(
    selections: Dict[str, Tuple[List[str], List[str]]],
) -> None:
    model = FakeModel(_response(selections))

    result = await select_research_candidates(_input(), model)

    assert model.calls == 1
    assert result.status is CandidateSelectionStatus.FAILED
    assert result.failure is not None
    assert result.failure.code is CandidateSelectionFailureCode.MODEL_OUTPUT_INVALID


@pytest.mark.parametrize(
    "raw",
    [
        (
            '{"domains":{'
            '"visit":{"focus_candidate_ids":["v1"],"search_candidate_ids":["v2"]},'
            '"visit":{"focus_candidate_ids":["v1"],"search_candidate_ids":["v2"]},'
            '"dining":{"focus_candidate_ids":["d1"],"search_candidate_ids":["d3"]}'
            "}}"
        ),
        (
            '{"domains":{'
            '"visit":{"focus_candidate_ids":["v1"],"search_candidate_ids":["v2"],'
            '"focus_candidate_ids":["v3"]},'
            '"dining":{"focus_candidate_ids":["d1"],"search_candidate_ids":["d3"]}'
            "}}"
        ),
    ],
)
async def test_duplicate_json_domain_or_field_keys_are_rejected(raw: str) -> None:
    model = FakeModel(raw)

    result = await select_research_candidates(_input(), model)

    assert model.calls == 1
    assert result.status is CandidateSelectionStatus.FAILED
    assert result.projection is None
    assert result.failure is not None
    assert result.failure.code is CandidateSelectionFailureCode.MODEL_OUTPUT_INVALID


def test_candidate_label_cannot_embed_internal_agent_or_tool_identifiers() -> None:
    for label in ("杭州 destination_researcher", "餐饮 maps_text_search"):
        with pytest.raises(ValidationError):
            AuthorizedCandidate(candidate_id="v1", domain=ResearchDomain.VISIT, label=label)


async def test_provider_failure_is_explicit_and_never_retried() -> None:
    model = FakeModel(error=RuntimeError("private provider detail"))

    result = await select_research_candidates(_input(), model)

    assert model.calls == 1
    assert result.status is CandidateSelectionStatus.FAILED
    assert result.projection is None
    assert result.failure is not None
    assert result.failure.code is CandidateSelectionFailureCode.MODEL_PROVIDER_FAILURE
    assert "private provider detail" not in result.canonical_json()


async def test_model_timeout_is_bounded_and_never_retried() -> None:
    model = SleepingModel()
    started_at = time.monotonic()

    result = await select_research_candidates(
        _input(), model, timeout_seconds=0.01
    )

    elapsed = time.monotonic() - started_at
    assert model.calls == 1
    assert elapsed < 1.0
    assert result.status is CandidateSelectionStatus.FAILED
    assert result.projection is None
    assert result.failure is not None
    assert result.failure.code is CandidateSelectionFailureCode.MODEL_TIMEOUT


async def test_invalid_timeout_is_rejected_before_any_model_call() -> None:
    model = FakeModel(_valid_variant_a())

    with pytest.raises(ValueError):
        await select_research_candidates(
            _input(),
            model,
            timeout_seconds=MAX_SELECTION_TIMEOUT_SECONDS + 1,
        )

    assert model.calls == 0
    assert DEFAULT_SELECTION_TIMEOUT_SECONDS <= MAX_SELECTION_TIMEOUT_SECONDS


def _max_size_candidates() -> List[AuthorizedCandidate]:
    domains = (
        ResearchDomain.VISIT,
        ResearchDomain.DINING,
        ResearchDomain.LODGING,
        ResearchDomain.LOCAL_TRANSPORT,
    )
    per_domain = MAX_TOTAL_CANDIDATES // len(domains)
    candidates: List[AuthorizedCandidate] = []
    for domain in domains:
        for index in range(per_domain):
            candidate_id = f"{domain.value[:4]}-{index}-" + "i" * (
                MAX_CANDIDATE_ID_LENGTH - len(domain.value[:4]) - len(str(index)) - 2
            )
            label_prefix = f"{domain.value.replace('_', ' ')} authorized place {index} "
            label = label_prefix + "x" * (
                MAX_CANDIDATE_LABEL_LENGTH - len(label_prefix)
            )
            assert len(candidate_id) == MAX_CANDIDATE_ID_LENGTH
            assert len(label) == MAX_CANDIDATE_LABEL_LENGTH
            candidates.append(
                AuthorizedCandidate(
                    candidate_id=candidate_id,
                    domain=domain,
                    label=label,
                )
            )
    return candidates


async def test_maximum_candidate_selection_and_prompt_sizes_are_supported() -> None:
    candidates = _max_size_candidates()
    domains = tuple({candidate.domain for candidate in candidates})
    selection_input = _input(candidates, domains)
    grouped: Dict[ResearchDomain, List[str]] = {domain: [] for domain in domains}
    for candidate in candidates:
        grouped[candidate.domain].append(candidate.candidate_id)
    raw = json.dumps(
        {
            "domains": {
                domain.value: {
                    "focus_candidate_ids": ids[:MAX_SELECTED_CANDIDATES_PER_KIND],
                    "search_candidate_ids": ids[
                        MAX_SELECTED_CANDIDATES_PER_KIND : MAX_SELECTED_CANDIDATES_PER_KIND * 2
                    ],
                }
                for domain, ids in grouped.items()
            }
        }
    )
    model = FakeModel(raw)

    result = await select_research_candidates(selection_input, model)

    assert len(candidates) == MAX_TOTAL_CANDIDATES
    assert all(
        len(
            [
                candidate
                for candidate in candidates
                if candidate.domain is domain
            ]
        )
        <= MAX_CANDIDATES_PER_DOMAIN
        for domain in domains
    )
    assert sum(len(message["content"]) for message in model.messages) <= MAX_PROMPT_CHARS
    assert model.calls == 1
    assert result.status is CandidateSelectionStatus.SELECTED
    assert result.failure is None
    assert result.projection is not None
    assert all(
        len(terms.focus_labels) == MAX_SELECTED_CANDIDATES_PER_KIND
        and len(terms.search_labels) == MAX_SELECTED_CANDIDATES_PER_KIND
        for terms in result.projection.values()
    )

    too_many_model = FakeModel(
        json.dumps(
            {
                "domains": {
                    domain.value: {
                        "focus_candidate_ids": ids[
                            : MAX_SELECTED_CANDIDATES_PER_KIND + 1
                        ],
                        "search_candidate_ids": ids[
                            MAX_SELECTED_CANDIDATES_PER_KIND + 1 :
                        ],
                    }
                    for domain, ids in grouped.items()
                }
            }
        )
    )
    too_many = await select_research_candidates(selection_input, too_many_model)
    assert too_many_model.calls == 1
    assert too_many.status is CandidateSelectionStatus.FAILED
    assert too_many.failure is not None
    assert (
        too_many.failure.code
        is CandidateSelectionFailureCode.MODEL_OUTPUT_INVALID
    )


@pytest.mark.parametrize("control", ["\n", "\x00", "\x7f"])
def test_candidate_labels_reject_control_characters(control: str) -> None:
    with pytest.raises(ValidationError):
        AuthorizedCandidate(
            candidate_id="v1",
            domain=ResearchDomain.VISIT,
            label=f"City{control}Museum",
        )


def test_input_caps_and_untrusted_shapes_are_rejected() -> None:
    with pytest.raises(ValidationError):
        CandidateSelectionInput(
            confirmation_digest="A" * 64,
            required_domains=frozenset({ResearchDomain.VISIT}),
            candidates=frozenset(
                {
                    AuthorizedCandidate(
                        candidate_id="v1",
                        domain=ResearchDomain.VISIT,
                        label="City Museum",
                    )
                }
            ),
        )
    with pytest.raises(ValidationError):
        CandidateSelectionInput(
            confirmation_digest=_DIGEST,
            required_domains=frozenset({ResearchDomain.VISIT}),
            candidates=frozenset(
                {
                    AuthorizedCandidate(
                        candidate_id="v1",
                        domain=ResearchDomain.VISIT,
                        label="City Museum",
                    )
                }
            ),
            unexpected_field=True,
        )
    with pytest.raises(ValidationError):
        AuthorizedCandidate(
            candidate_id="v1",
            domain=ResearchDomain.VISIT,
            label="   ",
        )
    with pytest.raises(ValidationError):
        AuthorizedCandidate(
            candidate_id="v1",
            domain=ResearchDomain.VISIT,
            label="candidate_1",
        )
    with pytest.raises(ValidationError):
        AuthorizedCandidate(
            candidate_id="v1",
            domain=ResearchDomain.VISIT,
            label="visit",
        )

    too_many_per_domain = [
        AuthorizedCandidate(
            candidate_id=f"v{index}",
            domain=ResearchDomain.VISIT,
            label=f"Place {index}",
        )
        for index in range(MAX_CANDIDATES_PER_DOMAIN + 1)
    ]
    with pytest.raises(ValidationError):
        _input(too_many_per_domain, (ResearchDomain.VISIT,))

    too_many_total = [
        AuthorizedCandidate(
            candidate_id=f"c{index}",
            domain=list(ResearchDomain)[index % len(ResearchDomain)],
            label=f"Place {index}",
        )
        for index in range(MAX_TOTAL_CANDIDATES + 1)
    ]
    with pytest.raises(ValidationError):
        _input(too_many_total, tuple(ResearchDomain))

    with pytest.raises(ValidationError):
        AuthorizedCandidate(
            candidate_id="v1",
            domain=ResearchDomain.VISIT,
            label="L" * (MAX_CANDIDATE_LABEL_LENGTH + 1),
        )
    with pytest.raises(ValidationError):
        AuthorizedCandidate(
            candidate_id="v" * (MAX_CANDIDATE_ID_LENGTH + 1),
            domain=ResearchDomain.VISIT,
            label="City Museum",
        )


async def test_selection_input_is_not_modified_and_prompt_is_deterministic() -> None:
    selection_input = _input()
    first_messages = build_selection_messages(selection_input)
    second_messages = build_selection_messages(selection_input)

    assert first_messages == second_messages
    assert selection_input.confirmation_digest == _DIGEST
    assert selection_input.candidates == frozenset(_CANDIDATES)
    assert "model-authored" not in first_messages[0]["content"]
