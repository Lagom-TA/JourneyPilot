"""共享错误前缀也是持久化 last_error 的一部分，不随模块迁移改值。"""

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
