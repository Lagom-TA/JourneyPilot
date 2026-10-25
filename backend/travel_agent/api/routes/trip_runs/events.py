from __future__ import annotations
import logging
from typing import Optional
from fastapi import APIRouter, Query
from travel_agent.bootstrap.registry import get_components
from travel_agent.api.schemas.runs import TripRunEventWindowResponse

from travel_agent.api.run_authorization import _get_authorized_run
from travel_agent.api.presenters.runs import _event_responses

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/trip-runs", tags=["trip-runs"])


@router.get("/{run_id}/events", response_model=TripRunEventWindowResponse)
async def list_trip_run_events(
    run_id: str,
    session_id: Optional[str] = Query(default=None),
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    retention_events: int = Query(default=500, ge=1, le=5000),
) -> TripRunEventWindowResponse:
    components = get_components()
    run = await _get_authorized_run(run_id, session_id=session_id)
    window = await components.trip_run_store.read_event_window(
        run_id,
        after_sequence=after_sequence,
        limit=limit,
        retention_events=retention_events,
    )

    current_bundle_id = await components.delivery_bundle_store.get_current_bundle_id(
        run_id
    )
    next_after = (
        window.events[-1].sequence
        if window.events
        else max(
            after_sequence,
            window.latest_sequence if window.window_expired else after_sequence,
        )
    )
    return TripRunEventWindowResponse(
        run_id=run_id,
        requested_after_sequence=window.requested_after_sequence,
        replay_floor_sequence=window.replay_floor_sequence,
        latest_sequence=window.latest_sequence,
        next_after_sequence=next_after,
        window_expired=window.window_expired,
        run_status=run.status.value,
        current_bundle_id=current_bundle_id,
        events=_event_responses(window.events),
    )
