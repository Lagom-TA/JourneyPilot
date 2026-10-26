"""按上游限制请求间隔的速率控制。"""

from __future__ import annotations

from typing import Dict
import asyncio
import time


class RateGate:
    """等到距上一次请求满 ``min_interval_seconds`` 再放行。"""

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
    """某个上游的进程级限速器，首次使用时创建。

    按上游而不是按调用方索引：访问同一上游的多个调用点必须共用间隔，否则各自
    执行的间隔之和会超过上游允许的频率。
    """

    gate = _GATES.get(key)
    if gate is None:
        gate = RateGate()
        _GATES[key] = gate
    return gate
