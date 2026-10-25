from __future__ import annotations
import logging
from travel_agent.runtime.run_contracts import TripRunStatus

logger = logging.getLogger(__name__)


class ChatDelivery:
    def __init__(self, *, run_id, use_deep_research, trip_run_store, bundle_store):
        self.run_id = run_id
        self.use_deep_research = use_deep_research
        self.trip_run_store = trip_run_store
        self.bundle_store = bundle_store
        self.delivery_ready_emitted = False
        self.run_terminal_emitted = False

    async def require_completed_bundle(self, current_bundle, workflow_bundle_id):
        current_run = await self.trip_run_store.get_run(self.run_id)
        if current_bundle is None:
            raise RuntimeError(
                "deep research ended without a persisted Delivery Bundle"
            )
        if current_run is None or current_run.status != TripRunStatus.COMPLETED:
            raise RuntimeError("deep research ended before durable TripRun completion")
        if (
            workflow_bundle_id
            and current_bundle.manifest.bundle_id != workflow_bundle_id
        ):
            raise RuntimeError(
                "workflow delivery differs from the current persisted Bundle"
            )

    async def completion_events(self, bundle_id):
        durable_events = await self.trip_run_store.list_events(
            self.run_id,
            after_sequence=0,
            limit=500,
        )
        ready_events = [
            event
            for event in durable_events
            if event.event_type == "delivery.ready"
            and event.payload.get("bundle_id") == bundle_id
        ]
        terminal_events = [
            event
            for event in durable_events
            if event.event_type == "run.terminal"
            and event.payload.get("bundle_id") == bundle_id
            and event.payload.get("status") == TripRunStatus.COMPLETED.value
        ]
        if len(ready_events) != 1 or len(terminal_events) != 1:
            raise RuntimeError(
                "deep research delivery events are missing or duplicated"
            )
        ready_event = ready_events[0]
        terminal_event = terminal_events[0]
        if ready_event.sequence >= terminal_event.sequence:
            raise RuntimeError("deep research delivery events are out of order")
        return ready_event, terminal_event

    async def load_durable_completed_delivery(self):
        """Recover the one immutable delivery after post-commit bookkeeping fails."""
        if not self.use_deep_research:
            return None
        current_run = await self.trip_run_store.get_run(self.run_id)
        current_bundle = await self.bundle_store.get_current(self.run_id)
        if (
            current_run is None
            or current_run.status != TripRunStatus.COMPLETED
            or current_bundle is None
        ):
            return None
        bundle_id = current_bundle.manifest.bundle_id
        durable_events = await self.trip_run_store.list_delivery_events(
            self.run_id,
            bundle_id,
        )
        ready_events = [
            event
            for event in durable_events
            if event.event_type == "delivery.ready"
            and event.payload.get("bundle_id") == bundle_id
        ]
        terminal_events = [
            event
            for event in durable_events
            if event.event_type == "run.terminal"
            and event.payload.get("bundle_id") == bundle_id
            and event.payload.get("status") == TripRunStatus.COMPLETED.value
        ]
        if len(ready_events) != 1 or len(terminal_events) != 1:
            raise RuntimeError(
                "completed deep research delivery events are missing or duplicated"
            )
        ready_event = ready_events[0]
        terminal_event = terminal_events[0]
        if ready_event.sequence >= terminal_event.sequence:
            raise RuntimeError(
                "completed deep research delivery events are out of order"
            )
        return current_bundle, ready_event, terminal_event
