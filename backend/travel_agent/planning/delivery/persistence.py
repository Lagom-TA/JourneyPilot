"""交付 Bundle 持久化。"""

from __future__ import annotations

from typing import Any

from travel_agent.planning.delivery.bundle import DeliveryBundle
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.operations import await_delivery_operation
from travel_agent.runtime.run_contracts import TripRunStatus
from travel_agent.storage.database import get_db_session
from travel_agent.storage.delivery_bundle_store import (
    BundleCommitKind,
    DeliveryBundleStore,
    InMemoryDeliveryBundleStore,
)
from travel_agent.storage.trip_run_store import InMemoryTripRunStore, TripRunStore


async def _commit_initial_delivery_atomically(
    *,
    bundle_store: DeliveryBundleStore,
    trip_store: TripRunStore,
    state: TravelAgentState,
    bundle: DeliveryBundle,
) -> DeliveryBundle:
    """把首个 Bundle 与其可见终态作为同一事务提交。"""

    if bundle.manifest.run_id != state.run_id:
        raise ValueError("delivery bundle run id does not match finalizer state")
    commit_kwargs = {
        "bundle": bundle,
        "kind": BundleCommitKind.CREATE,
        "idempotency_key": f"{state.run_id}:delivery:create",
        "metadata": {"operation": "initial_delivery"},
    }

    async def complete(current: DeliveryBundle, *, session: Any | None = None) -> None:
        if current.manifest.bundle_id != bundle.manifest.bundle_id:
            raise RuntimeError("persisted delivery bundle is not the current bundle")
        completed, _ready_event, _terminal_event = await await_delivery_operation(
            trip_store.complete_delivery(
                state.run_id,
                bundle_id=current.manifest.bundle_id,
                manifest=current.manifest.model_dump(mode="json"),
                **({"session": session} if session is not None else {}),
            ),
            operation="trip_run_complete_delivery",
        )
        if completed.status != TripRunStatus.COMPLETED:
            raise RuntimeError("TripRun completion was not durably recorded")

    if isinstance(bundle_store, InMemoryDeliveryBundleStore) and isinstance(
        trip_store, InMemoryTripRunStore
    ):
        bundle_snapshot = bundle_store.snapshot_for_initial_delivery()
        trip_snapshot = trip_store.snapshot_for_initial_delivery()
        try:
            commit = await await_delivery_operation(
                bundle_store.commit(**commit_kwargs),
                operation="delivery_bundle_commit",
            )
            current = await await_delivery_operation(
                bundle_store.get_current(state.run_id),
                operation="delivery_bundle_readback",
            )
            if (
                current is None
                or current.manifest.bundle_id != commit.bundle.manifest.bundle_id
            ):
                raise RuntimeError(
                    "persisted delivery bundle is not the current bundle"
                )
            await complete(current)
            return current
        except Exception:
            bundle_store.restore_initial_delivery(bundle_snapshot)
            trip_store.restore_initial_delivery(trip_snapshot)
            raise

    if isinstance(bundle_store, InMemoryDeliveryBundleStore) or isinstance(
        trip_store, InMemoryTripRunStore
    ):
        raise RuntimeError("delivery finalizer requires matched persistence stores")

    # checkpoint 使用另一个连接池；只有这个共享事务能证明交付完成。
    async with get_db_session() as session:
        commit = await await_delivery_operation(
            bundle_store.commit(**commit_kwargs, session=session),
            operation="delivery_bundle_commit",
        )
        current = await await_delivery_operation(
            bundle_store.get_current_in_session(session, state.run_id),
            operation="delivery_bundle_readback",
        )
        if (
            current is None
            or current.manifest.bundle_id != commit.bundle.manifest.bundle_id
        ):
            raise RuntimeError("persisted delivery bundle is not the current bundle")
        await complete(current, session=session)
        return current
