"""checkpoint 反序列化日志的去重。"""

from __future__ import annotations

from typing import Optional
from typing import Set
from typing import Tuple
import logging


CHECKPOINT_SERDE_LOGGER_NAME = "langgraph.checkpoint.serde.jsonplus"


_UNREGISTERED_TYPE_MESSAGE_PREFIX = "Deserializing unregistered type"


class UnregisteredCheckpointTypeDedup(logging.Filter):
    """同一种类型只保留第一条 "unregistered type" 警告。

    一次 Run 会把同一批类型实体反复送进 checkpointer，同一警告可能重复数百次，
    掩盖该次 Run 的其他日志。

    只丢弃这一条消息的重复项：每个 ``(module, name)`` 的第一条仍会带上游的
    「未来版本将阻止该类型」提示与具体类型名。这里不关闭 logger、不调整级别，
    也不影响该 logger 上的其他记录；库的「已阻止反序列化」警告与这一条共用
    logger，且不是重复噪声。
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
    """把去重过滤器挂到 checkpoint serde logger 上，只挂一次。"""
    target = logger or logging.getLogger(CHECKPOINT_SERDE_LOGGER_NAME)
    for existing in target.filters:
        if isinstance(existing, UnregisteredCheckpointTypeDedup):
            return existing
    installed = UnregisteredCheckpointTypeDedup()
    target.addFilter(installed)
    return installed
