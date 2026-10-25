"""Integrations places contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from typing import Dict
from typing import Literal


PlaceProviderFailureCode = Literal[
    "provider_unavailable",
    "provider_unparseable",
    "provider_invalid_payload",
]


class NominatimPlaceSearchError(RuntimeError):
    """The global place provider could not return a valid response.

    ``code`` 是必填的。三种失败在运维上要区别对待，而路由会把 message 丢掉、换成一句
    本地化字符串 —— 只靠英文 message 区分，区别就在边界上没了。
    判据放在异常上，**不靠 message 匹配**：靠 message 认失败类型是另一条隐式合同。
    """

    def __init__(self, message: str, *, code: PlaceProviderFailureCode) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class NominatimSearchObservation:
    """One ``/search`` answer plus when the provider actually produced it.

    ``observed_at`` is the provider observation instant, not the moment this
    process read it: on a reuse it is the timestamp of the original live call.
    Callers that turn this into evidence must publish *this* value, never
    ``now`` — that difference is the whole reason the raw body is reusable.
    """

    items: list[Dict[str, Any]]
    observed_at: datetime
    origin: Literal["live", "cache"]
