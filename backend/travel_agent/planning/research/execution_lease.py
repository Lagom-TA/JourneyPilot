"""检查研究任务是否仍持有运行租约。"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from travel_agent.runtime.journal import current_execution_lease

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutionLeaseObservation:
    live: bool
    reason_code: str
    token: Optional[str] = None


def _field(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, Mapping) else getattr(value, name, None)


def _lease_store(config: Optional[Mapping[str, Any]]) -> Any:
    configurable = (config or {}).get("configurable", {})
    if isinstance(configurable, Mapping) and configurable.get("run_execution_store") is not None:
        return configurable["run_execution_store"]
    try:
        from travel_agent.bootstrap.registry import get_components

        return getattr(get_components(), "run_execution_store", None)
    except RuntimeError:
        return None


async def observe_execution_lease(state: Any, config: Optional[Mapping[str, Any]] = None) -> ExecutionLeaseObservation:
    token = current_execution_lease.get()
    if not token:
        return ExecutionLeaseObservation(False, "lease_token_missing")
    run_id = str(getattr(state, "run_id", "") or "")
    if not run_id:
        return ExecutionLeaseObservation(False, "lease_run_missing", str(token))
    store = _lease_store(config)
    if store is None or not hasattr(store, "get"):
        return ExecutionLeaseObservation(False, "lease_store_unavailable", str(token))
    try:
        execution = await store.get(run_id)
    except Exception as exc:
        logger.warning("运行租约读取失败 run_id=%s: %s", run_id, exc)
        return ExecutionLeaseObservation(False, "lease_store_error", str(token))
    if execution is None or str(_field(execution, "lease_token") or "") != str(token):
        return ExecutionLeaseObservation(False, "lease_token_mismatch", str(token))
    expiry = _field(execution, "lease_expires_at")
    if isinstance(expiry, str):
        try:
            expiry = datetime.datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        except ValueError:
            expiry = None
    if not isinstance(expiry, datetime.datetime):
        return ExecutionLeaseObservation(False, "lease_expired", str(token))
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=datetime.timezone.utc)
    if expiry <= datetime.datetime.now(datetime.timezone.utc):
        return ExecutionLeaseObservation(False, "lease_expired", str(token))
    return ExecutionLeaseObservation(True, "", str(token))
