"""Storage checkpoint logging."""

from __future__ import annotations

from typing import Optional
from typing import Set
from typing import Tuple
import logging


CHECKPOINT_SERDE_LOGGER_NAME = "langgraph.checkpoint.serde.jsonplus"


_UNREGISTERED_TYPE_MESSAGE_PREFIX = "Deserializing unregistered type"


class UnregisteredCheckpointTypeDedup(logging.Filter):
    """Keep the first "unregistered type" warning per type, drop its repeats.

    One gated deep run replays the same handful of typed entities through the
    checkpointer thousands of times, so eight distinct types arrive as roughly
    220 identical WARNING lines that bury the rest of the run's log.

    Only the repeats are dropped, and only for this one message: the first
    warning per ``(module, name)`` still carries the upstream "this will be
    blocked in a future version" notice and names exactly which type would need
    registering. Nothing here silences the logger, raises its level, or touches
    any other record on it — which matters because the library's *blocked*
    deserialization warning shares this logger and is not repetitive noise.
    """

    def __init__(self) -> None:
        super().__init__()
        self._reported: Set[Tuple[str, str]] = set()

    def filter(self, record: logging.LogRecord) -> bool:
        if not str(record.msg).startswith(_UNREGISTERED_TYPE_MESSAGE_PREFIX):
            return True

        args = record.args
        if not isinstance(args, tuple) or len(args) < 2:
            return True
        key = (str(args[0]), str(args[1]))
        if key in self._reported:
            return False
        self._reported.add(key)
        return True


def install_checkpoint_serde_log_dedup(
    logger: Optional[logging.Logger] = None,
) -> UnregisteredCheckpointTypeDedup:
    """Attach the de-duplicating filter to the checkpoint serde logger once."""
    target = logger or logging.getLogger(CHECKPOINT_SERDE_LOGGER_NAME)
    for existing in target.filters:
        if isinstance(existing, UnregisteredCheckpointTypeDedup):
            return existing
    installed = UnregisteredCheckpointTypeDedup()
    target.addFilter(installed)
    return installed
