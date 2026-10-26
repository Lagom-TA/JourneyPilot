"""行程组合使用的每日可用时段。"""

from __future__ import annotations

from travel_agent.planning.requirements.intent_contracts import IntentKind
from travel_agent.planning.requirements.intent_contracts import IntentTarget
from travel_agent.planning.requirements.intent_contracts import TimeWindowIntentValue
from travel_agent.planning.requirements.route_legs import (
    build_required_long_distance_legs,
)
from travel_agent.planning.requirements.route_legs import (
    explicit_cross_day_return_required,
)
from travel_agent.planning.research.candidates import TransportCandidate
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.provider_scope_ids import provider_evidence_scope_id


def daily_planning_windows(state, catalog):
    draft = state.minimum_delivery_draft
    if draft is None:
        return []

    custom_activity_hours = any(
        intent.target in {IntentTarget.TRIP, IntentTarget.ITINERARY, IntentTarget.VISIT}
        and intent.kind != IntentKind.MUST_EXCLUDE
        and (
            intent.kind == IntentKind.TIME_WINDOW
            or isinstance(intent.value, TimeWindowIntentValue)
            or any(
                word in intent.value.model_dump_json().casefold()
                for word in (
                    "夜游",
                    "夜景",
                    "夜间",
                    "evening",
                    "night",
                    "日出",
                    "sunrise",
                )
            )
        )
        for intent in (state.intent_spec.active_items if state.intent_spec else [])
    )
    legs = build_required_long_distance_legs(
        state.controlled_trip_identity or {},
        cross_day_return_required=explicit_cross_day_return_required(
            state.user_query or ""
        ),
    )
    scopes = {
        provider_evidence_scope_id(
            run_id=state.run_id,
            constraint_pack_revision=state.constraint_pack_revision,
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
                "apply_capacity": not custom_activity_hours,
                "transport_anchors": applied,
                "assumption": (
                    "用户已指定活动时段，以下默认日间窗口不用于裁剪候选；排程须按用户时段重新计算。"
                    if custom_activity_hours
                    else ""
                )
                + "默认09:00–18:00活动；抵达后预留45分钟、离开前60分钟，另留用餐/休息/市内移动。按用户时段、实际路线和预约调整，不能当作已核验接驳时间。",
            }
        )
    return windows
