"""记忆抽取计量（进程级累计）。

记忆抽取在每轮对话结束后异步触发，用 fast 模型把 facts / portrait 写入
memory_facts 与知识图谱，不属于关键路径。运维通过 ``/api/status`` 与日志确认
抽取成败。

- 进程内累计：自进程启动起累计计数（同 Prometheus counter 语义），
  ``/api/status`` 读取快照，不按 run 管理生命周期。
- 线程安全：并发的后台抽取可能同时结算，统一由锁保护。
- 计数口径：``attempted`` 为实际发起抽取的轮次（已过滤空消息与匿名用户）；
  ``succeeded`` 为模型返回并处理完成（可能本轮无值可写）；``failed`` 为
  模型调用、解析或写入任一环节抛错；``facts_written`` / ``portraits_written``
  为实际入库计数。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class _ExtractionStats:
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    facts_written: int = 0
    portraits_written: int = 0
    last_error: Optional[str] = None


class MemoryExtractionStats:
    """进程级记忆抽取计量（抽取器结算点写入，/api/status 读取）。"""

    def __init__(self) -> None:
        self._stats = _ExtractionStats()
        self._lock = threading.Lock()

    def record_attempt(self) -> None:
        with self._lock:
            self._stats.attempted += 1

    def record_success(self, *, facts: int, portraits: int) -> None:
        with self._lock:
            self._stats.succeeded += 1
            self._stats.facts_written += max(0, facts)
            self._stats.portraits_written += max(0, portraits)

    def record_failure(self, error: str) -> None:
        with self._lock:
            self._stats.failed += 1
            self._stats.last_error = error

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            s = self._stats
            return {
                "attempted": s.attempted,
                "succeeded": s.succeeded,
                "failed": s.failed,
                "facts_written": s.facts_written,
                "portraits_written": s.portraits_written,
                "last_error": s.last_error,
            }


_stats_singleton: Optional[MemoryExtractionStats] = None


def get_memory_extraction_stats() -> MemoryExtractionStats:
    """进程级记忆抽取计量单例（抽取器写入，系统状态读取）。"""
    global _stats_singleton
    if _stats_singleton is None:
        _stats_singleton = MemoryExtractionStats()
    return _stats_singleton


def reset_memory_extraction_stats() -> None:
    global _stats_singleton
    _stats_singleton = None
