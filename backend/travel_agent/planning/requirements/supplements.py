from __future__ import annotations

from typing import NoReturn

from travel_agent.planning.run_errors import RunNotAcceptingSupplement
from travel_agent.runtime.run_contracts import TripRunStatus


async def reject_running_supplement(
    *, run, trip_run_store, delivery_bundle_store
) -> NoReturn:
    current = run
    seen = set()
    while current is not None and current.run_id not in seen:
        seen.add(current.run_id)
        if current.session_id != run.session_id or current.user_id != run.user_id:
            break
        if current.status == TripRunStatus.COMPLETED:
            bundle = await delivery_bundle_store.get_current(current.run_id)
            if bundle is not None and bundle.manifest.run_id == current.run_id:
                raise RunNotAcceptingSupplement(has_delivery=True)
        if not current.parent_run_id:
            break
        current = await trip_run_store.get_run(current.parent_run_id)
    raise RunNotAcceptingSupplement()
