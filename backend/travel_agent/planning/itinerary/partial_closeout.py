from __future__ import annotations

from collections import defaultdict
from typing import Mapping, Sequence

from travel_agent.planning.itinerary.adjacency import _destination_stay_window
from travel_agent.planning.itinerary.connectors import LocalConnectorGap
from travel_agent.planning.itinerary.draft import (
    ItineraryCompositionDraft,
    ItineraryCompositionError,
    placement_occurrence_key,
)
from travel_agent.planning.research.candidates import (
    DiningCandidate,
    LodgingCandidate,
    ResearchCandidate,
    TransportCandidate,
    VisitCandidate,
)
from travel_agent.planning.research.catalog import RecommendationCatalog


OvertimedConnector = tuple[LocalConnectorGap, int, int]


def _endpoint_name(
    gap: LocalConnectorGap,
    *,
    leaving: bool,
    skeleton: ItineraryCompositionDraft,
    candidates: Mapping[str, ResearchCandidate],
) -> str:
    endpoint = gap.from_endpoint if leaving else gap.to_endpoint
    if endpoint is not None and endpoint.name.strip():
        return endpoint.name.strip()
    entry_key = gap.from_entry_key if leaving else gap.to_entry_key
    place_id = gap.from_place_id if leaving else gap.to_place_id
    for day in skeleton.days:
        if day.day_id != gap.day_id:
            continue
        for placement in day.placements:
            if placement_occurrence_key(day.day_id, placement) != entry_key:
                continue
            if placement.placement_kind in {"visit", "dining"}:
                if placement.authored_place is not None:
                    return placement.authored_place.name
                candidate = candidates.get(placement.candidate_id or "")
                if isinstance(candidate, VisitCandidate):
                    return candidate.name
                if isinstance(candidate, DiningCandidate):
                    return candidate.branch_name
            else:
                candidate = candidates.get(placement.candidate_id or "")
                if isinstance(candidate, TransportCandidate):
                    return (candidate.to_endpoint if leaving else candidate.from_endpoint).name
    for candidate in candidates.values():
        if isinstance(candidate, VisitCandidate) and candidate.place_id == place_id:
            return candidate.name
        if isinstance(candidate, DiningCandidate) and candidate.place_id == place_id:
            return candidate.branch_name
        if isinstance(candidate, LodgingCandidate) and candidate.place_id == place_id:
            return candidate.property_name
        if isinstance(candidate, TransportCandidate):
            for candidate_endpoint in (candidate.from_endpoint, candidate.to_endpoint):
                if candidate_endpoint.place_id == place_id and candidate_endpoint.name.strip():
                    return candidate_endpoint.name.strip()
    return f"未命名地点（{place_id}）"


def _conflict_detail(
    conflict: OvertimedConnector,
    skeleton: ItineraryCompositionDraft,
    candidates: Mapping[str, ResearchCandidate],
) -> str:
    gap, duration, window = conflict
    origin = _endpoint_name(gap, leaving=True, skeleton=skeleton, candidates=candidates)
    destination = _endpoint_name(gap, leaving=False, skeleton=skeleton, candidates=candidates)
    detail = (
        f"{gap.day_date.isoformat()} {origin}至{destination}接驳需{duration}分钟，"
        f"时间窗口为{window}分钟"
    )
    if window < 0:
        detail += f"（接驳开始时间比最晚到达时间晚{abs(window)}分钟）"
    return detail


def _cross_day_groups(
    skeleton: ItineraryCompositionDraft,
    candidates: Mapping[str, ResearchCandidate],
) -> dict[str, set[str]]:
    """只按已选长途班次的跨日引用连接日期。"""
    day_ids_by_date: dict[object, set[str]] = defaultdict(set)
    owners_by_candidate: dict[str, set[str]] = defaultdict(set)
    day_by_id = {day.day_id: day for day in skeleton.days}
    for day in skeleton.days:
        day_ids_by_date[day.date].add(day.day_id)
        for placement in day.placements:
            if placement.placement_kind != "transport" or not placement.candidate_id:
                continue
            candidate = candidates.get(placement.candidate_id)
            if isinstance(candidate, TransportCandidate) and candidate.transport_class == "long_distance":
                owners_by_candidate[candidate.candidate_id].add(day.day_id)

    links = {day.day_id: set() for day in skeleton.days}
    for candidate_id, owners in owners_by_candidate.items():
        candidate = candidates[candidate_id]
        if not isinstance(candidate, TransportCandidate):
            continue
        service_days = set(owners)
        if (
            candidate.departure_at is not None
            and candidate.arrival_at is not None
            and candidate.departure_at.date() != candidate.arrival_at.date()
        ):
            service_days.update(day_ids_by_date.get(candidate.departure_at.date(), set()))
            service_days.update(day_ids_by_date.get(candidate.arrival_at.date(), set()))
        if len({day_by_id[day_id].date for day_id in service_days}) < 2:
            continue
        for day_id in service_days:
            links[day_id].update(service_days - {day_id})
    return links


def _append_unresolved(existing: list[str], message: str) -> list[str]:
    # 聚合到最后一项，既保留原有内容，也满足每日最多八项的约束。
    unique = list(dict.fromkeys(item.strip() for item in existing if item.strip()))
    if any(message in item.split("\n") for item in unique):
        return unique
    if len(unique) < 8:
        return [*unique, message]
    return [*unique[:7], f"{unique[7]}\n{message}"]


def build_partial_closeout(
    skeleton: ItineraryCompositionDraft,
    catalog: RecommendationCatalog,
    overtimed: Sequence[OvertimedConnector],
) -> ItineraryCompositionDraft:
    """清空冲突及相关跨日班次的日期，保留可安全交付的其余日期。"""
    payload = skeleton.model_dump()
    if not overtimed:
        return ItineraryCompositionDraft.model_validate(payload)

    candidates = catalog.candidate_index()
    day_by_id = {day.day_id: day for day in skeleton.days}
    conflicts_by_day: dict[str, list[str]] = defaultdict(list)
    for conflict in overtimed:
        gap = conflict[0]
        day = day_by_id.get(gap.day_id)
        if day is None or day.date != gap.day_date:
            raise ItineraryCompositionError("connector conflict does not match the skeleton day")
        conflicts_by_day[day.day_id].append(_conflict_detail(conflict, skeleton, candidates))

    links = _cross_day_groups(skeleton, candidates)
    affected: set[str] = set()
    reasons_by_day: dict[str, list[str]] = {}
    for day in skeleton.days:
        if day.day_id in affected or day.day_id not in conflicts_by_day:
            continue
        component: set[str] = set()
        pending = [day.day_id]
        while pending:
            current = pending.pop()
            if current in component:
                continue
            component.add(current)
            pending.extend(links[current] - component)
        details = list(dict.fromkeys(
            detail
            for other in skeleton.days
            if other.day_id in component
            for detail in conflicts_by_day.get(other.day_id, [])
        ))
        affected.update(component)
        for day_id in component:
            reasons_by_day[day_id] = details

    affected_dates = {day_by_id[day_id].date for day_id in affected}
    for day in payload["days"]:
        design = day["day_design"]
        if day["day_id"] in affected:
            details = "；".join(reasons_by_day[day["day_id"]])
            notice = f"{day['date'].isoformat()} 行程尚未安排：{details}；相关安排需重新规划。"
            if design is None:
                design = {"free_time": [], "unresolved": []}
                day["day_design"] = design
            design["unresolved"] = _append_unresolved(design["unresolved"], notice)
            design["free_time"] = []
            day["placements"] = []
        elif design is not None:
            # 休息时段按实际日期物化，即使它写在了其他 Day 的设计中。
            design["free_time"] = [
                item for item in design["free_time"]
                if item["planned_start"].date() not in affected_dates
            ]

    retained_lodging = []
    for candidate_id in skeleton.lodging_candidate_ids:
        candidate = candidates.get(candidate_id)
        if not isinstance(candidate, LodgingCandidate):
            raise ItineraryCompositionError("lodging choice references an unknown or non-lodging candidate")
        window = _destination_stay_window(
            skeleton, candidate.destination_id, candidate.check_in_date, candidate.check_out_date
        )
        # 住宿仅在入住和退房日期投影；不能让它重新填入已清空的时间线。
        if window is None or not affected_dates.intersection(window):
            retained_lodging.append(candidate_id)
    payload["lodging_candidate_ids"] = retained_lodging
    return ItineraryCompositionDraft.model_validate(payload)
