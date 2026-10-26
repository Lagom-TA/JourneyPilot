from __future__ import annotations

import contextlib
import contextvars
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, Literal, Optional
from .deadlines import clear_process_deadline_anchor

if TYPE_CHECKING:
    from .budget import RunBudgetSnapshot


current_run_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_run_id",
    default=None,
)


current_node: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_node",
    default=None,
)


current_agent: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_agent",
    default=None,
)


run_ts_anchor: contextvars.ContextVar[Optional[float]] = contextvars.ContextVar(
    "run_ts_anchor",
    default=None,
)


NodeLifecycleStatus = Literal["started", "completed", "retrying", "failed"]


NodeLifecycleSink = Callable[[Dict[str, Any]], Awaitable[None]]


node_lifecycle_sink: contextvars.ContextVar[Optional[NodeLifecycleSink]] = (
    contextvars.ContextVar(
        "node_lifecycle_sink",
        default=None,
    )
)


current_run_deadline: contextvars.ContextVar[Optional[Any]] = contextvars.ContextVar(
    "current_run_deadline",
    default=None,
)


current_run_budget: contextvars.ContextVar[Optional[RunBudgetSnapshot]] = (
    contextvars.ContextVar(
        "current_run_budget",
        default=None,
    )
)


ModelWindow = Literal["research", "composition"]


current_model_window: contextvars.ContextVar[ModelWindow] = contextvars.ContextVar(
    "current_model_window",
    default="research",
)


@contextlib.contextmanager
def run_attribution(
    run_id: Optional[str],
    *,
    node: Optional[str] = "workflow",
    agent: Optional[str] = "workflow",
    lifecycle_sink: Optional[NodeLifecycleSink] = None,
):
    """在图执行外层设置粗粒度的 Run 归属。

    具体节点包装会覆盖 ``current_node`` 与 ``current_agent``；这一层覆盖没有
    ``current_run_id`` 的图入口与快速路径边界，避免用量记录静默跳过它们。
    """
    token_run = current_run_id.set(str(run_id) if run_id else None)
    token_node = current_node.set(node)
    token_agent = current_agent.set(agent)
    token_lifecycle_sink = node_lifecycle_sink.set(lifecycle_sink)
    try:
        yield
    finally:
        # 恢复时按持久化的已耗时下限重建本进程锚点。
        clear_process_deadline_anchor()
        node_lifecycle_sink.reset(token_lifecycle_sink)
        current_agent.reset(token_agent)
        current_node.reset(token_node)
        current_run_id.reset(token_run)
