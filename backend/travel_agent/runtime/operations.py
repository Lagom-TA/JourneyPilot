from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Optional
from .context import (
    ModelWindow,
    current_model_window,
    current_node,
    current_run_deadline,
)
from .cancellation import check_cancel_requested
from .deadlines import DeadlineObservation, observe_run_deadline


class ModelWindowClosed(RuntimeError):
    """模型、provider 或工具调用在自己的时间窗关闭后才发起。

    与 :class:`RunCancelled` 刻意区分：用户没有取消 TripRun，调用方应走确定性
    收口，而不是发出取消终态。
    """

    def __init__(
        self,
        operation: str,
        observation: DeadlineObservation,
        window: ModelWindow,
    ) -> None:
        self.operation = operation
        self.observation = observation
        self.window = window
        super().__init__(
            f"{window} window closed before {operation} "
            f"(elapsed={observation.elapsed_seconds:.3f}s)"
        )


class DeliveryDeadlineExceeded(RuntimeError):
    """仅交付阶段的操作越过了快照中的交付截止时间。"""

    def __init__(self, operation: str, observation: DeadlineObservation) -> None:
        self.operation = operation
        self.observation = observation
        super().__init__(
            f"delivery deadline exceeded before {operation} "
            f"(elapsed={observation.elapsed_seconds:.3f}s)"
        )


def observe_current_run_deadline() -> tuple[
    Optional[Any], Optional[DeadlineObservation]
]:
    """读取当前 durable deadline，不重置其预算。"""

    deadline = current_run_deadline.get()
    if deadline is None:
        return None, None
    observed, observation = observe_run_deadline(deadline)
    current_run_deadline.set(observed)
    return observed, observation


def remaining_model_seconds(operation: str) -> Optional[float]:
    """返回当前上下文可用的模型时间；窗口关闭时拒绝新调用。

    窗口来自 :data:`current_model_window`：研究调用须在 closeout 前完成，
    行程编排使用更晚的窗口。剩余秒数始终来自 Run 自己的已封存快照，而不是本进程
    的配置默认值。快照是跨进程的最终事实，因此可用预算必须与阶段判定使用同一组
    数字：之后修改 ``run_deadline`` 不会给在跑的 Run 追加时间，也不会缩短它。
    """

    check_cancel_requested(current_node.get())
    deadline, observation = observe_current_run_deadline()
    if observation is None or deadline is None:
        return None
    window = current_model_window.get()
    if window == "composition":
        window_seconds = deadline.composition_seconds
        closed = observation.composition_closed
    else:
        window_seconds = deadline.closeout_seconds
        closed = observation.research_closed
    remaining = max(0.0, window_seconds - observation.elapsed_seconds)
    if closed or remaining <= 0:
        raise ModelWindowClosed(operation, observation, window)
    return remaining


def remaining_delivery_seconds(operation: str) -> Optional[float]:
    """返回共用的交付预算；截止后拒绝工作。

    ``observation.remaining_seconds`` 就是该预算，口径是 Run 自己快照里的交付
    截止时间，原因同 :func:`remaining_model_seconds`。
    """

    check_cancel_requested(current_node.get())
    _deadline, observation = observe_current_run_deadline()
    if observation is None:
        return None
    remaining = observation.remaining_seconds
    if observation.phase == "expired" or remaining <= 0:
        raise DeliveryDeadlineExceeded(operation, observation)
    return remaining


async def await_model_operation(awaitable: Awaitable[Any], *, operation: str) -> Any:
    """在一个模型/provider 操作自己的窗口内等待它完成。"""

    try:
        remaining = remaining_model_seconds(operation)
    except BaseException:
        # 调用点通常会先构造协程再传进来。deadline 同步拒绝该操作时，关闭尚未
        # 启动的协程以避免 unawaited-coroutine 警告。
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()
        raise
    if remaining is None:
        return await awaitable
    try:
        return await asyncio.wait_for(awaitable, timeout=remaining)
    except asyncio.TimeoutError as exc:
        _deadline, observation = observe_current_run_deadline()
        if observation is None:  # pragma: no cover - 上下文被重置的防御分支
            raise
        raise ModelWindowClosed(
            operation, observation, current_model_window.get()
        ) from exc


async def await_delivery_operation(awaitable: Awaitable[Any], *, operation: str) -> Any:
    """在共用的交付截止时间内等待收尾操作完成。"""

    try:
        remaining = remaining_delivery_seconds(operation)
    except BaseException:
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()
        raise
    if remaining is None:
        return await awaitable
    try:
        return await asyncio.wait_for(awaitable, timeout=remaining)
    except asyncio.TimeoutError as exc:
        _deadline, observation = observe_current_run_deadline()
        if observation is None:  # pragma: no cover - 上下文被重置的防御分支
            raise
        raise DeliveryDeadlineExceeded(operation, observation) from exc
