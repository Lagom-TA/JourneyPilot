"""Serialize one session's intake assessment and draft changes.

The application runs a single API process; locks protect its concurrent requests.
The database remains the source of truth for the saved intake.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any
from weakref import WeakValueDictionary


_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


def intake_session_lock(session_id: str) -> asyncio.Lock:
    lock = _locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[session_id] = lock
    return lock


def intake_fingerprint(intake: Any) -> str | None:
    if intake is None:
        return None
    payload = intake.model_dump(mode="json")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class IntakeChangedBeforeStart(RuntimeError):
    """A newer intake exists, so this Run must not start from a stale assessment."""
