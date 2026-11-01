"""行程组合使用的每日可用时段。"""

from __future__ import annotations

from travel_agent.planning.requirements.route_legs import (
    build_required_long_distance_legs,
)
from travel_agent.planning.research.candidates import TransportCandidate
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.provider_scope_ids import provider_evidence_scope_id


def daily_planning_windows(state, catalog):
    draft = state.minimum_delivery_draft
    if draft is None:
        return []

    legs = build_required_long_distance_legs(
        state.controlled_trip_identity or {},
        cross_day_return_required=False,
    )
    scopes = {
        provider_evidence_scope_id(
            run_id=state.run_id,
            worker_kind="transport_researcher",
            research_domain=ResearchDomain.LONG_DISTANCE_TRANSPORT,
            candidate_kind=None,
            transport_class="long_distance",
            target_identity=None,
            route_leg=leg,
        ): leg
        for leg in legs
    }
    anchors = [
        candidate
        for candidate in catalog.candidate_index().values()
        if isinstance(candidate, TransportCandidate)
        and candidate.transport_class == "long_distance"
        and candidate.departure_at is not None
        and candidate.arrival_at is not None
    ]
    windows = []
    for shell in draft.day_shells:
        start, end = 9 * 60, 18 * 60
        applied = []
        for candidate in anchors:
            leg = scopes.get(candidate.provider_evidence_scope_id)
            if leg is None:
                continue
            if leg.to_place_id == shell.destination_id:
                if (
                    candidate.departure_at.date()
                    <= shell.date
                    < candidate.arrival_at.date()
                ):
                    start = end
                elif candidate.arrival_at.date() == shell.date:
                    stamp = candidate.arrival_at
                    start = max(start, stamp.hour * 60 + stamp.minute + 45)
                    applied.append({"role": "arrival", "at": stamp.isoformat()})
            if (
                leg.from_place_id == shell.destination_id
                and candidate.departure_at.date() == shell.date
            ):
                stamp = candidate.departure_at
                end = min(end, stamp.hour * 60 + stamp.minute - 60)
                applied.append({"role": "departure", "at": stamp.isoformat()})
        usable = max(0, end - start)

        visit_minutes = max(0, usable - min(150, round(usable * 0.3)))
        windows.append(
            {
                "day_id": shell.day_id,
                "date": shell.date.isoformat(),
                "destination_id": shell.destination_id,
                "suggested_start": f"{min(start, 1440) // 60:02d}:{min(start, 1440) % 60:02d}",
                "suggested_end": f"{max(end, 0) // 60:02d}:{max(end, 0) % 60:02d}",
                "visit_minutes": visit_minutes,
                "apply_capacity": True,
                "transport_anchors": applied,
                "assumption": "默认09:00–18:00活动；抵达后预留45分钟、离开前60分钟，另留用餐/休息/市内移动。按用户时段、实际路线和预约调整，不能当作已核验接驳时间。",
            }
        )
    return windows
