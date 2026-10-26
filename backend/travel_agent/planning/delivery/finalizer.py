"""交付定稿节点。"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from langchain_core.runnables import RunnableConfig

from travel_agent.planning.delivery.assembly import assemble_delivery_bundle
from travel_agent.planning.delivery.completion import (
    DeliveryFinalizationError,
    _require_sealed_completion_generation,
)
from travel_agent.planning.delivery.evidence_basis import (
    PublicProjectionContractViolation,
)
from travel_agent.planning.delivery.persistence import (
    _commit_initial_delivery_atomically,
)
from travel_agent.planning.delivery.public.bundle import public_delivery_bundle
from travel_agent.planning.outcomes import (
    DeliveryFailureRecord,
    InternalFailureClass,
)
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.operations import (
    DeliveryDeadlineExceeded,
    await_delivery_operation,
    remaining_delivery_seconds,
)
from travel_agent.runtime.run_contracts import TripRunStatus
from travel_agent.storage.delivery_bundle_store import DeliveryBundleStore
from travel_agent.storage.trip_run_store import TripRunStore

DEFAULT_PERSIST_RETRY_BUDGET = 3


def _config_value(config: Optional[RunnableConfig], key: str) -> Any:
    return (config or {}).get("configurable", {}).get(key)


async def _mark_failed(
    trip_store: TripRunStore,
    state: TravelAgentState,
    record: DeliveryFailureRecord,
) -> None:
    failure_payload = {
        "failure_class": record.failure_class.value,
        "operation": record.operation,
        "attempts": record.attempts,
    }
    try:
        run = await trip_store.get_run(state.run_id)
        if run is not None and run.status != TripRunStatus.RUNNING:
            await trip_store.append_event_once(
                state.run_id,
                "run.delivery_failed",
                {**failure_payload, "run_status": run.status.value},
                idempotency_key=f"{state.run_id}:delivery_failed:{record.operation}",
            )
            return
        if run is not None and run.status == TripRunStatus.RUNNING:
            await trip_store.transition_status(
                state.run_id,
                TripRunStatus.FAILED,
                current_node="delivery_finalizer",
                error_code=record.failure_class.value,
                error_message=record.public_message,
                event_type="run.delivery_failed",
                payload=failure_payload,
            )
    except Exception:
        return


async def delivery_finalizer_node(
    state: TravelAgentState,
    config: Optional[RunnableConfig] = None,
) -> Dict[str, Any]:
    bundle_store = _config_value(config, "delivery_bundle_store")
    trip_store = _config_value(config, "trip_run_store")
    if not isinstance(bundle_store, DeliveryBundleStore):
        raise ValueError("delivery_bundle_store is required")
    if not isinstance(trip_store, TripRunStore):
        raise ValueError("trip_run_store is required")
    try:
        _require_sealed_completion_generation(state)
    except Exception as exc:
        record = DeliveryFailureRecord(
            failure_class=InternalFailureClass.CONTRACT_VIOLATION,
            operation="validate_sealed_completion_generation",
            attempts=1,
            retry_exhausted=True,
            public_message="旅行方案未能完成，请重新生成。",
        )
        await _mark_failed(trip_store, state, record)
        raise DeliveryFinalizationError(record, exc) from exc
    try:
        remaining_delivery_seconds("delivery_finalizer")
    except DeliveryDeadlineExceeded as exc:
        record = DeliveryFailureRecord(
            failure_class=InternalFailureClass.PERSISTENCE_FAILURE,
            operation="delivery_deadline_guard",
            attempts=1,
            retry_exhausted=True,
            public_message="旅行方案未能在交付时限内完成。",
        )
        await _mark_failed(trip_store, state, record)
        raise DeliveryFinalizationError(record, exc) from exc
    try:
        bundle = assemble_delivery_bundle(state)
    except Exception as exc:
        record = DeliveryFailureRecord(
            failure_class=InternalFailureClass.CONTRACT_VIOLATION,
            operation="assemble_delivery_bundle",
            attempts=1,
            retry_exhausted=True,
            public_message="旅行方案未能完成，请重新生成。",
        )
        await _mark_failed(trip_store, state, record)
        raise DeliveryFinalizationError(record, exc) from exc
    try:
        public_delivery_bundle(bundle)
    except PublicProjectionContractViolation as exc:
        record = DeliveryFailureRecord(
            failure_class=InternalFailureClass.PROJECTION_FAILURE,
            operation="public_delivery_projection_dry_run",
            attempts=1,
            retry_exhausted=True,
            public_message="旅行方案未能完成，请重新生成。",
        )
        await _mark_failed(trip_store, state, record)
        raise DeliveryFinalizationError(record, exc) from exc

    retry_budget = max(
        1,
        min(
            int(
                _config_value(config, "delivery_persist_retry_budget")
                or DEFAULT_PERSIST_RETRY_BUDGET
            ),
            5,
        ),
    )
    last_error: Exception = RuntimeError("delivery persistence did not run")
    for attempt in range(1, retry_budget + 1):
        try:
            current = await _commit_initial_delivery_atomically(
                bundle_store=bundle_store,
                trip_store=trip_store,
                state=state,
                bundle=bundle,
            )
            return {
                "delivery_bundle": current,
                "delivery_persisted": True,
                "delivery_failure": None,
                "is_completed": True,
            }
        except Exception as exc:
            last_error = exc
            if isinstance(exc, DeliveryDeadlineExceeded):
                break
            if attempt < retry_budget:
                try:
                    await await_delivery_operation(
                        asyncio.sleep(0),
                        operation="delivery_persist_retry_backoff",
                    )
                except DeliveryDeadlineExceeded as deadline_exc:
                    last_error = deadline_exc
                    break

    record = DeliveryFailureRecord(
        failure_class=InternalFailureClass.PERSISTENCE_FAILURE,
        operation="persist_bundle_then_complete_run",
        attempts=retry_budget,
        retry_exhausted=True,
        public_message="旅行方案未能完成，请重新生成。",
    )
    await _mark_failed(trip_store, state, record)
    raise DeliveryFinalizationError(record, last_error) from last_error
