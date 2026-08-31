"""持久化 worker error 前缀的读写行为。"""

from __future__ import annotations

import pytest

from travel_agent.agents.orchestrator.provider_failure import (
    classify_provider_failure,
    is_provider_or_model_failure,
)
from travel_agent.agents.research_packet_output import ResearchPacketOutputError
from travel_agent.agents.worker_errors import (
    PREFIX_PROVIDER_CAPABILITY,
    PREFIX_PROVIDER_DETERMINISTIC,
    PREFIX_PROVIDER_EMPTY,
    PREFIX_PROVIDER_TRANSIENT,
    PREFIX_SCHEMA_GATE,
    format_worker_last_error,
)


_NEUTRAL = "planning halted"


@pytest.mark.parametrize(
    ("prefix", "category", "reason_code"),
    [
        (PREFIX_SCHEMA_GATE, "deterministic", "provider_deterministic_failure"),
        (PREFIX_PROVIDER_DETERMINISTIC, "deterministic", "provider_deterministic_failure"),
        (PREFIX_PROVIDER_TRANSIENT, "transient", "provider_transient_failure"),
        (PREFIX_PROVIDER_EMPTY, "incomplete", "provider_empty_result"),
        (PREFIX_PROVIDER_CAPABILITY, "incomplete", "provider_capability_declined"),
    ],
)
def test_persisted_failure_prefixes_have_stable_reader_verdict(
    prefix: str, category: str, reason_code: str
) -> None:
    result = classify_provider_failure(f"{prefix} {_NEUTRAL}")
    assert (result.category, result.reason_code) == (category, reason_code)
    assert is_provider_or_model_failure(f"{prefix} {_NEUTRAL}") is True


def test_schema_gate_prefix_preserves_transient_retryability() -> None:
    result = classify_provider_failure(f"{PREFIX_SCHEMA_GATE} connection reset")
    assert (result.category, result.reason_code) == (
        "transient",
        "provider_transient_failure",
    )


def test_writer_emits_specific_prefixes_for_typed_round_outcomes() -> None:
    assert format_worker_last_error(
        ValueError("no results"), provider_empty_round=True
    ).startswith(f"{PREFIX_PROVIDER_EMPTY} ")
    assert format_worker_last_error(
        ValueError("unsupported date"), provider_capability_round=True
    ).startswith(f"{PREFIX_PROVIDER_CAPABILITY} ")
    assert format_worker_last_error(ResearchPacketOutputError("invalid packet")).startswith(
        f"{PREFIX_SCHEMA_GATE} "
    )


def test_writer_is_idempotent_for_an_already_prefixed_error() -> None:
    once = format_worker_last_error(ValueError("boom"))
    assert format_worker_last_error(ValueError(once)) == once
