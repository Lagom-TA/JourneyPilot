"""Runtime rate gate."""

from __future__ import annotations

from typing import Dict
import asyncio
import time


class RateGate:
    """Delay until ``min_interval_seconds`` has passed since the last request."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def acquire(self, min_interval_seconds: float) -> None:
        async with self._lock:
            wait = min_interval_seconds - (time.monotonic() - self._last_request_at)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()


_GATES: Dict[str, RateGate] = {}


def rate_gate_for(key: str) -> RateGate:
    """The process-wide gate for one upstream, created on first use.

    Keyed rather than per-caller: two call sites that talk to the same upstream
    have to share the spacing, or each one honours an interval the upstream never
    agreed to.
    """

    gate = _GATES.get(key)
    if gate is None:
        gate = RateGate()
        _GATES[key] = gate
    return gate
