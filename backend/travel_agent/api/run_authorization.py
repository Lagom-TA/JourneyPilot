from __future__ import annotations
from typing import Optional
from fastapi import HTTPException
from travel_agent.bootstrap.registry import get_components


async def _get_authorized_run(run_id: str, *, session_id: Optional[str] = None):
    components = get_components()
    detail = await components.trip_run_store.get_detail(run_id, event_limit=0)
    if detail is None:
        raise HTTPException(status_code=404, detail="TripRun 不存在")
    if session_id and detail.run.session_id != session_id:
        raise HTTPException(status_code=403, detail="无权访问该 TripRun")
    return detail.run
