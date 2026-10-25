"""Planning research failure protocol."""

from __future__ import annotations

from typing import Final


PREFIX_SCHEMA_GATE: Final = "schema_gate:"


PREFIX_PROVIDER_EMPTY: Final = "provider_empty:"


PREFIX_PROVIDER_CAPABILITY: Final = "provider_capability:"


PREFIX_PROVIDER_TRANSIENT: Final = "provider_transient:"


PREFIX_PROVIDER_DETERMINISTIC: Final = "provider_deterministic:"


PREFIX_WORKER_FAILED: Final = "worker_failed:"


KNOWN_PREFIXES: Final = (
    PREFIX_SCHEMA_GATE,
    PREFIX_PROVIDER_EMPTY,
    PREFIX_PROVIDER_CAPABILITY,
    PREFIX_PROVIDER_TRANSIENT,
    PREFIX_PROVIDER_DETERMINISTIC,
    PREFIX_WORKER_FAILED,
)
