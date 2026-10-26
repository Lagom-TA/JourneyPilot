"""Planning itinerary day capacity."""

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
import re


def default_walking_days(state, skeleton):
    """Conservative opt-in to measured short-walk comparison, never accessibility proof.

    Any mobility uncertainty or explicit local mode restriction leaves the
    existing user-directed routing policy in charge. Weather cutoffs are planning
    defaults; absent observations do not count as benign weather.
    """
    pack = state.constraint_pack or {}
    items = [
        item
        for key in ("hard_constraints", "soft_preferences")
        for item in pack.get(key, [])
        if item.get("status") == "active"
    ]
    for item in items:
        params = item.get("params") or {}
        if item.get("category") in {
            "elderly_mobility",
            "health_condition",
            "child_friendly",
        }:
            return set()
        if item.get("category") == "transport_constraint" and (
            item in pack.get("hard_constraints", [])
            or params.get("locked_local_mode")
            or params.get("excluded_local_modes")
            or any(
                mode in {"walk", "bike", "drive", "taxi", "ride_hailing"}
                for mode in params.get("preferred_local_modes", [])
            )
        ):
            return set()
        if any(
            "walk" in str(key).lower() or "mobility" in str(key).lower()
            for key in params
        ):
            return set()
    intent_text = state.intent_spec.model_dump_json() if state.intent_spec else ""
    if re.search(
        r"少走|不走|不能走|步行.{0,12}(?:上限|最多|不超过)|轮椅|老人|父母|婴|幼儿|行动不便|膝|腿伤|mobility|wheelchair|limited.walk|avoid.walk|elderly",
        (state.user_query or "") + intent_text,
        re.I,
    ):
        return set()
    weather = state.weather_context
    if weather is None:
        return set()
    eligible = set()
    for day in skeleton.days:
        report = next(
            (
                item
                for item in weather.days
                if item.date == day.date and item.destination_id == day.destination_id
            ),
            None,
        )
        if report is None or report.data_kind != "forecast" or report.alert_ids:
            continue
        values = (
            report.precipitation_probability_pct,
            report.precipitation_mm,
            report.wind_gust_kph,
            report.high_c,
            report.low_c,
        )
        if any(value is None for value in values):
            continue
        if (
            report.precipitation_probability_pct <= 40
            and report.precipitation_mm <= 2
            and report.wind_gust_kph <= 35
            and report.high_c <= 30
            and report.low_c >= 5
        ):
            eligible.add(day.day_id)
    return eligible


def disclose_default_walking(workspace, gaps):
    pairs = {
        (gap.from_place_id, gap.to_place_id) for gap in gaps if gap.compare_default_walk
    }
    candidates = workspace.recommendation_catalog.candidate_index()
    if not any(
        leg.selected_mode.value == "walk"
        and leg.lineage is not None
        and leg.lineage.candidate_id in candidates
        and candidates[leg.lineage.candidate_id].selected_mode.value == "walk"
        and leg.distance_meters is not None
        and 0 < leg.distance_meters <= 1000
        and 0 < leg.duration_minutes <= 15
        and (leg.from_endpoint.place_id, leg.to_endpoint.place_id) in pairs
        for leg in workspace.itinerary.transport_legs
    ):
        return workspace
    note = (
        "短程接驳已比较地图步行与公共交通：仅在步行预计不更慢、单段不超过15分钟且1公里时建议步行，"
        "每天新增独立步行接驳累计不超过30分钟。这些是规划默认上限，不含景区内步行，"
        "也不代表无台阶或无障碍；出发前请按体力和现场天气调整。"
    )
    itinerary = workspace.itinerary.model_copy(
        update={
            "important_notes": [*workspace.itinerary.important_notes, note],
        }
    )
    return workspace.model_copy(update={"itinerary": itinerary})


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
