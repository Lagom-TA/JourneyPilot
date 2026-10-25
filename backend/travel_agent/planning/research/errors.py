"""Planning research errors."""

from __future__ import annotations

from travel_agent.planning.research.failure_protocol import (
    KNOWN_PREFIXES as _KNOWN_PREFIXES,
)
from travel_agent.planning.research.failure_protocol import (
    PREFIX_PROVIDER_CAPABILITY,
    PREFIX_PROVIDER_DETERMINISTIC,
    PREFIX_PROVIDER_EMPTY,
    PREFIX_PROVIDER_TRANSIENT,
    PREFIX_SCHEMA_GATE,
    PREFIX_WORKER_FAILED,
)
from travel_agent.planning.research.output.policy import ResearchPacketOutputError
from travel_agent.planning.research.provider_failure import (
    _DETERMINISTIC_MARKERS,
    _TRANSIENT_MARKERS,
)

_QUERY_MISS_MARKERS = (
    "found no executable route",
    "no results",
    "empty result",
)


def _already_prefixed(text: str) -> bool:
    lowered = text.casefold()
    return any(lowered.startswith(prefix.casefold()) for prefix in _KNOWN_PREFIXES)


def format_worker_last_error(
    exc: BaseException,
    *,
    provider_empty_round: bool = False,
    provider_capability_round: bool = False,
) -> str:
    """Return a classifier-friendly last_error string for research workers."""
    text = str(exc).strip() or type(exc).__name__
    if _already_prefixed(text):
        return text

    if provider_capability_round:
        return f"{PREFIX_PROVIDER_CAPABILITY} {text}"

    if provider_empty_round:
        return f"{PREFIX_PROVIDER_EMPTY} {text}"

    if isinstance(exc, ResearchPacketOutputError):
        return f"{PREFIX_SCHEMA_GATE} {text}"

    lowered = text.casefold()

    if (
        "research packet" in lowered
        or "worker output" in lowered
        or "json object" in lowered
        or "json parse" in lowered
        or ("validation error" in lowered and "research" in lowered)
    ):
        return f"{PREFIX_SCHEMA_GATE} {text}"

    if any(marker in lowered for marker in _DETERMINISTIC_MARKERS):
        return f"{PREFIX_PROVIDER_DETERMINISTIC} {text}"
    if any(marker in lowered for marker in _TRANSIENT_MARKERS):
        return f"{PREFIX_PROVIDER_TRANSIENT} {text}"
    if any(marker in text or marker in lowered for marker in _QUERY_MISS_MARKERS):
        return f"{PREFIX_PROVIDER_EMPTY} {text}"

    return f"{PREFIX_WORKER_FAILED} {text}"
