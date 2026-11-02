"""首次交付提交所需的事务快照能力。

交付持久化需要一个“失败可整体回滚”的测试执行路径；该能力由存储实现自行声明，
产品代码只依赖协议，不依赖任何具体实现。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class InitialDeliverySnapshotCapable(Protocol):
    """仓储可以在首次交付提交前后捕获与恢复内存状态。"""

    def snapshot_for_initial_delivery(self) -> Any: ...

    def restore_initial_delivery(self, snapshot: Any) -> None: ...
