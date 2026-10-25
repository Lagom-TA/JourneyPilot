from __future__ import annotations
from typing import Optional
from travel_agent.config.loader import get_settings
from travel_agent.runtime.run_lease import RunLeaseKeeper
from travel_agent.runtime.cancellation import RunControlHandle
from .errors import ExecutionAlreadyOwned


class RequestExecutionLease:
    """Lease-loss callbacks target only this request's executor handle."""

    def __init__(self, execution_store):
        self.execution_store = execution_store
        self.control_handle: Optional[RunControlHandle] = None

    async def claim(
        self,
        run_id: str,
        *,
        checkpoint_id: Optional[str] = None,
    ) -> RunLeaseKeeper:
        """抢下这个 Run 的执行权。抢不到就不开始 —— 两个执行器同时跑一个 Run 会写出
        两份互相覆盖的状态，而用户看到的是随机一份。"""

        lease_settings = get_settings().run_control
        keeper = RunLeaseKeeper(
            self.execution_store,
            run_id,
            lease_seconds=lease_settings.lease_seconds,
            heartbeat_seconds=lease_settings.lease_heartbeat_seconds,
            failure_threshold=lease_settings.lease_heartbeat_failure_threshold,
            on_lease_lost=lambda reason: (
                self.control_handle.request_stop("lease_lost")
                if self.control_handle is not None
                else None
            ),
        )
        if not await keeper.claim(last_safe_checkpoint_id=checkpoint_id):
            raise ExecutionAlreadyOwned()
        return keeper
