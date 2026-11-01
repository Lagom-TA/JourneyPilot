"""同会话聊天请求的串行锁。

应用是单 API 进程；锁保护它的并发请求。数据库仍是会话事实的来源。
"""

from __future__ import annotations

import asyncio
from weakref import WeakValueDictionary


_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


def intake_session_lock(session_id: str) -> asyncio.Lock:
    lock = _locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[session_id] = lock
    return lock
