from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional
from .context import current_run_id, current_node


RunStopReason = Literal["user_cancel", "lease_lost", "stream_exit"]


@dataclass(frozen=True)
class StopVerdict:
    """一个停止原因收敛成什么。"""

    #: 记进 `trip_runs` 的终态名。
    terminal_status: str
    #: 落进事件 payload 的 reason。
    payload_reason: str
    #: 有值时写进 `error_code`。
    error_code: Optional[str] = None
    #: 是否是用户自己的决定（决定要不要先写一条 cancel_requested）。
    user_decision: bool = False


STOP_VERDICTS: Dict[str, StopVerdict] = {
    "user_cancel": StopVerdict(
        terminal_status="cancelled",
        payload_reason="user_cancelled",
        user_decision=True,
    ),
    "lease_lost": StopVerdict(
        terminal_status="interrupted",
        payload_reason="executor_lease_lost",
        error_code="executor_lease_lost",
    ),
    "stream_exit": StopVerdict(
        terminal_status="interrupted",
        payload_reason="stream_exit",
        error_code="stream_exit_before_terminal",
    ),
}


def stop_verdict(reason: str) -> StopVerdict:
    return STOP_VERDICTS.get(reason, STOP_VERDICTS["stream_exit"])


class RunCancelled(Exception):
    """协作式停止信号到达节点边界时抛出。"""

    def __init__(
        self,
        run_id: str,
        node_name: Optional[str] = None,
        *,
        reason: RunStopReason = "user_cancel",
    ) -> None:
        self.run_id = run_id
        self.node_name = node_name
        self.reason = reason
        label = f" at {node_name}" if node_name else ""
        super().__init__(f"TripRun {run_id} stopped ({reason}){label}")


SupplementAppliedSink = Callable[[List[str], str, Dict[str, Any]], Awaitable[None]]


SupplementRejectedSink = Callable[[List[str], str, Dict[str, Any]], Awaitable[None]]


@dataclass
class RunControlHandle:
    run_id: str
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    delivery_ready_event: asyncio.Event = field(default_factory=asyncio.Event)
    #: 已 claim 但还没落进 state 的追加要求，每条带着自己的 `command_id`。
    supplements: List[Dict[str, str]] = field(default_factory=list)
    stop_reason: RunStopReason = "user_cancel"
    #: 有新的 durable command 时被 set，让协调器立刻去读表而不必等下一个轮询周期。
    wake_event: asyncio.Event = field(default_factory=asyncio.Event)
    supplement_applied_sink: Optional[SupplementAppliedSink] = None
    supplement_rejected_sink: Optional[SupplementRejectedSink] = None

    def request_stop(self, reason: RunStopReason = "user_cancel") -> None:
        self.stop_reason = reason
        self.cancel_event.set()

    def mark_delivery_ready(self) -> None:
        """阻止本轮后续研究写入在交付物定型之后发布内容。

        durable Bundle 的身份仍是最终事实。这个事件只防止同时结束的 worker 在
        finalizer 已持久化该身份之后发布旧内容。
        """
        self.delivery_ready_event.set()

    def add_supplement(self, category: str, content: str, *, command_id: str) -> None:
        self.supplements.append(
            {"command_id": command_id, "category": category, "content": content}
        )

    def pending_supplements(self) -> List[Dict[str, str]]:
        """还没落进 state 的追加要求。

        **取走不等于清空**：节点抛异常时它返回的 state update 会被丢掉，那条要求也就没有
        生效。留在这里，下一个节点边界再试一次。
        """

        return list(self.supplements)

    async def mark_supplements_applied(
        self,
        command_ids: List[str],
        *,
        node: str,
        result: Dict[str, Any],
    ) -> None:
        applied = {str(value) for value in command_ids if str(value).strip()}
        if not applied:
            return
        self.supplements = [
            item for item in self.supplements if item.get("command_id") not in applied
        ]
        if self.supplement_applied_sink is not None:
            await self.supplement_applied_sink(sorted(applied), node, result)

    async def mark_supplements_rejected(
        self,
        command_ids: List[str],
        *,
        node: str,
        result: Dict[str, Any],
    ) -> None:
        rejected = {str(value) for value in command_ids if str(value).strip()}
        if not rejected:
            return
        self.supplements = [
            item for item in self.supplements if item.get("command_id") not in rejected
        ]
        if self.supplement_rejected_sink is not None:
            await self.supplement_rejected_sink(sorted(rejected), node, result)


class RunControlRegistry:
    """按 run id 索引的进程内 handle。**唤醒通道，不是命令的存放处。**"""

    def __init__(self) -> None:
        self._handles: Dict[str, RunControlHandle] = {}

    def register(self, run_id: str) -> RunControlHandle:
        handle = RunControlHandle(run_id=run_id)
        self._handles[run_id] = handle
        return handle

    def get(self, run_id: Optional[str]) -> Optional[RunControlHandle]:
        if not run_id:
            return None
        return self._handles.get(run_id)

    def unregister(
        self, run_id: Optional[str], handle: Optional["RunControlHandle"] = None
    ) -> None:
        """注销。给了 ``handle`` 就只在这一格还是它的时候删。

        被接管的那条流清理时按 run_id 盲删，删掉的是接管者的 handle，此后用户的
        取消在任何节点边界上都观察不到。
        """

        if not run_id:
            return
        if handle is not None and self._handles.get(run_id) is not handle:
            return
        self._handles.pop(run_id, None)

    def request_stop(self, run_id: str, reason: RunStopReason = "user_cancel") -> bool:
        """进程内的停止信号。用于失去租约这类**不来自用户**、没有 durable command 的停止。"""

        handle = self.get(run_id)
        if handle is None:
            return False
        handle.request_stop(reason)
        return True

    def notify(self, run_id: str) -> bool:
        """告诉执行器「表里有新命令」。返回本进程是否正在跑这个 run。

        返回 False **不是**拒绝：命令已经落库，执行器下一次轮询照样看得见。这个布尔值只
        用于日志与回执里的观察，不参与任何正确性判断。
        """

        handle = self.get(run_id)
        if handle is None:
            return False
        handle.wake_event.set()
        return True

    def clear(self) -> None:
        self._handles.clear()


run_control_registry = RunControlRegistry()


def check_cancel_requested(node_name: Optional[str] = None) -> None:
    """进程内停止标记已置位时抛出 ``RunCancelled``。

    停止是协作式的：检查发生在节点入口、ReAct 迭代边界以及每次工具结果之后。
    正在进行的 LLM 流或单次工具 HTTP 调用可能仍会完成并到达下一个检查点；
    延迟上界是这一轮在途调用，而不是强制终止进程。
    """
    run_id = current_run_id.get()
    handle = run_control_registry.get(run_id)
    if handle is not None and handle.cancel_event.is_set():
        raise RunCancelled(
            run_id or handle.run_id,
            node_name or current_node.get(),
            reason=handle.stop_reason,
        )
