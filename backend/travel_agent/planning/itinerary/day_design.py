"""把每日设计（日主题与主动休息）落到已物化的行程上。"""

from __future__ import annotations

from travel_agent.planning.delivery.travel_content import public_selection_text
from travel_agent.planning.itinerary.models import CustomBlock
from travel_agent.planning.itinerary.models import TimelineEntryRef
from travel_agent.planning.references import EntityType
from travel_agent.planning.workspace import TripWorkspaceV2
import hashlib


def _final_day_note(day, stops, blocks):
    """用已物化的停留点与休息时段拼出当天安排说明。"""
    parts = []
    for ref in day.timeline:
        stop = stops.get(ref.entity_id)
        if stop is not None:
            when = (
                f"{stop.planned_start:%H:%M}–{stop.planned_end:%H:%M} "
                if stop.planned_start and stop.planned_end
                else ""
            )
            reason = public_selection_text(stop.selection_reason, fallback="")
            parts.append(f"{when}{stop.name}。{reason}".rstrip("。.!！ "))
        else:
            block = next(
                (item for item in blocks if item.item_id == ref.entity_id), None
            )
            if block is not None and block.planned_start and block.planned_end:
                parts.append(
                    f"{block.planned_start:%H:%M}–{block.planned_end:%H:%M} {block.note}".rstrip(
                        "。.!！ "
                    )
                )
    return f"第{day.day}天安排：" + "。".join(parts) + "。" if parts else None


def apply_day_design(workspace, composition):
    itinerary = workspace.itinerary
    designs = {day.day_id: day.day_design for day in composition.days if day.day_design}
    # 休息时段按实际日期落位：写错所属 Day 时仍落到日期对应的那一天；
    # 跨日时段或日期不在行程内的时段无法落位，跳过。
    day_id_by_date = {day.date: day.day_id for day in itinerary.day_plans}
    free_time_by_day: dict[str, list] = {}
    for design in designs.values():
        for planned in design.free_time:
            start, end = planned.planned_start, planned.planned_end
            target_day_id = day_id_by_date.get(start.date())
            if target_day_id is None or end.date() != start.date():
                continue
            free_time_by_day.setdefault(target_day_id, []).append(planned)
    blocks = list(itinerary.custom_blocks)
    notes = list(itinerary.important_notes)
    days = []
    stops = {
        stop.item_id: stop for stop in [*itinerary.visit_stops, *itinerary.dining_stops]
    }
    routes = {leg.transport_leg_id: leg for leg in itinerary.transport_legs}
    for day in itinerary.day_plans:
        planned_blocks = free_time_by_day.get(day.day_id, [])
        if designs.get(day.day_id) is None and not planned_blocks:
            days.append(day)
            continue
        timeline = list(day.timeline)
        for planned in sorted(planned_blocks, key=lambda block: block.planned_start):
            start, end = planned.planned_start, planned.planned_end
            insertion = len(timeline)
            for index, existing in enumerate(timeline):
                stop = stops.get(existing.entity_id)
                leg = routes.get(existing.entity_id)
                at = stop.planned_start if stop else leg.departure_at if leg else None
                if at is not None and at >= end:
                    insertion = index
                    if (
                        index
                        and timeline[index - 1].entity_type == EntityType.TRANSPORT_LEG
                    ):
                        previous = routes.get(timeline[index - 1].entity_id)
                        if previous and previous.transport_class != "long_distance":
                            insertion -= 1
                    break
            if insertion == len(timeline):
                last_stop_index = next(
                    (
                        index
                        for index in range(len(timeline) - 1, -1, -1)
                        if timeline[index].entity_id in stops
                    ),
                    None,
                )
                if last_stop_index is not None:
                    insertion = last_stop_index + 1
            previous_stop = None
            for previous_ref in reversed(timeline[:insertion]):
                if previous_ref.entity_type == EntityType.TRANSPORT_LEG:
                    break
                previous_stop = stops.get(previous_ref.entity_id)
                if previous_stop is not None:
                    break
            digest = hashlib.sha256(
                f"{day.day_id}|{start.isoformat()}".encode()
            ).hexdigest()[:20]
            block = CustomBlock(
                item_id=f"free_time_{digest}",
                day_id=day.day_id,
                title="自由休息",
                note=(
                    f"在{previous_stop.name}附近休息。"
                    if previous_stop is not None
                    else "自由休息。"
                ),
                planned_start=start,
                planned_end=end,
                duration_minutes=round((end - start).total_seconds() / 60),
            )
            blocks.append(block)
            ref = TimelineEntryRef(
                entry_id=f"entry_{digest}",
                entity_type=EntityType.CUSTOM_BLOCK,
                entity_id=block.item_id,
            )
            timeline.insert(insertion, ref)
        days.append(day.model_copy(update={"timeline": timeline}))
    for day in days:
        note = _final_day_note(day, stops, blocks)
        if note:
            notes.append(note)
    updated = itinerary.model_copy(
        update={"day_plans": days, "custom_blocks": blocks, "important_notes": notes}
    )
    return TripWorkspaceV2.model_validate(
        workspace.model_copy(update={"itinerary": updated}).model_dump()
    )
