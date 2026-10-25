"""Integrations provider environment."""

from __future__ import annotations

from typing import Any
from typing import Literal
from typing import Mapping
from typing import Optional


DataEnvironment = Literal["production", "sandbox"]


SANDBOX_EVIDENCE_NOTE = (
    "本方案中部分交通班次的依据来自供应商的开发（沙箱）环境，"
    "班次、时刻与价格仅供规划参考，不可直接预订。"
)


_VALID: frozenset[str] = frozenset({"production", "sandbox"})


_ALWAYS_PRODUCTION_PROVIDERS = frozenset(
    {
        "transitous",
        "nominatim",
        "amap",
        "12306",
        "open-meteo",
    }
)


def snapshot_data_environment(
    snapshot: Optional[Mapping[str, Any]],
    *,
    provider_name: str,
) -> DataEnvironment:
    """Read the environment out of one provider snapshot.

    ``snapshot`` is a ``SourceRecord.snapshot``, which has two shapes depending on
    whether the record came through the snapshot cache: the sanitized provider
    payload itself, or a Tool Envelope wrapping it under ``sanitized_result``.
    Both are read here so a cache hit and a live call cannot disagree about the
    environment of the same response.

    A provider that declares its environment is believed.  A provider with no test
    environment is production by identity.  Anything else raises: an unlabelled
    response from a supplier that *does* have a sandbox is exactly the case this
    field exists for, and guessing "production" there is the original defect.
    """

    declared = _declared(snapshot)
    if declared is not None:
        return declared
    if provider_name.strip().lower() in _ALWAYS_PRODUCTION_PROVIDERS:
        return "production"
    raise ValueError(
        f"provider {provider_name!r} did not state which data environment answered"
    )


def _declared(snapshot: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not isinstance(snapshot, Mapping):
        return None
    for payload in (snapshot, snapshot.get("sanitized_result")):
        if not isinstance(payload, Mapping):
            continue
        value = payload.get("data_environment")
        if isinstance(value, str) and value in _VALID:
            return value
    return None
