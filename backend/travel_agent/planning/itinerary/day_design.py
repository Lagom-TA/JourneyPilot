"""Planning itinerary day design."""

from __future__ import annotations

from datetime import timedelta
from travel_agent.planning.delivery.travel_content import public_selection_text
from travel_agent.planning.itinerary.draft import ItineraryCompositionError
from travel_agent.planning.itinerary.models import CustomBlock
from travel_agent.planning.itinerary.models import TimelineEntryRef
from travel_agent.planning.itinerary.time_buffers import planned_boarding_buffer_minutes
from travel_agent.planning.references import EntityType
from travel_agent.planning.workspace import TripWorkspaceV2
import hashlib


def _final_day_note(day, stops, blocks):
    """Describe the materialized stops and explicit rest windows."""
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
    blocks = list(itinerary.custom_blocks)
    notes = list(itinerary.important_notes)
    days = []
    stops = {
        stop.item_id: stop for stop in [*itinerary.visit_stops, *itinerary.dining_stops]
    }
    routes = {leg.transport_leg_id: leg for leg in itinerary.transport_legs}
    for day in itinerary.day_plans:
        design = designs.get(day.day_id)
        if design is None:
            days.append(day)
            continue
        occupied = []
        for ref in day.timeline:
            stop = stops.get(ref.entity_id)
            leg = routes.get(ref.entity_id)
            start = stop.planned_start if stop else leg.departure_at if leg else None
            end = stop.planned_end if stop else leg.arrival_at if leg else None
            if start is not None and end is not None:
                occupied.append((start, end))
                if leg and leg.transport_class == "long_distance":
                    occupied.append(
                        (
                            start
                            - timedelta(
                                minutes=planned_boarding_buffer_minutes(
                                    leg.selected_mode
                                )
                            ),
                            start,
                        )
                    )

        for index, ref in enumerate(day.timeline):
            leg = routes.get(ref.entity_id)
            if (
                leg is None
                or leg.transport_class == "long_distance"
                or leg.departure_at is not None
                or leg.duration_minutes is None
            ):
                continue
            following_at = None
            for following in day.timeline[index + 1 :]:
                stop = stops.get(following.entity_id)
                anchor = routes.get(following.entity_id)
                following_at = (
                    stop.planned_start
                    if stop
                    else anchor.departure_at
                    if anchor
                    else None
                )
                if (
                    following_at is not None
                    and anchor
                    and anchor.transport_class == "long_distance"
                ):
                    following_at -= timedelta(
                        minutes=planned_boarding_buffer_minutes(anchor.selected_mode)
                    )
                if following_at is not None:
                    break
            if following_at is not None:
                occupied.append(
                    (
                        following_at - timedelta(minutes=leg.duration_minutes),
                        following_at,
                    )
                )
        timeline = list(day.timeline)
        for planned in sorted(design.free_time, key=lambda block: block.planned_start):
            start, end = planned.planned_start, planned.planned_end
            if start.date() != day.date or end.date() != day.date:
                raise ItineraryCompositionError(
                    f"free time must belong to day {day.day_id}"
                )
            for left, right in occupied:
                if start < right and end > left:
                    raise ItineraryCompositionError(
                        f"day {day.day_id} free time {start.isoformat()}–{end.isoformat()} "
                        f"overlaps activity or transport {left.isoformat()}–{right.isoformat()}; "
                        "revise the complete draft while preserving the requested rest"
                    )
            occupied.append((start, end))

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
                    trailing = [
                        routes[ref.entity_id]
                        for ref in timeline[last_stop_index + 1 :]
                        if ref.entity_id in routes
                    ]
                    if trailing and all(
                        leg.transport_class != "long_distance" for leg in trailing
                    ):
                        if any(leg.duration_minutes is None for leg in trailing):
                            raise ItineraryCompositionError(
                                "free time before hotel needs known transfer duration"
                            )
                        arrival = end + timedelta(
                            minutes=sum(leg.duration_minutes for leg in trailing)
                        )
                        if arrival.date() != day.date:
                            raise ItineraryCompositionError(
                                "free time leaves no same-day hotel transfer window"
                            )
                        insertion = last_stop_index + 1
            previous_stop = None
            for previous_ref in reversed(timeline[:insertion]):
                if previous_ref.entity_type == EntityType.TRANSPORT_LEG:
                    break
                previous_stop = stops.get(previous_ref.entity_id)
                if previous_stop is not None:
                    break
            if (
                previous_stop is None
                or previous_stop.planned_end is None
                or previous_stop.planned_end > start
            ):
                raise ItineraryCompositionError(
                    f"day {day.day_id} free time {start.isoformat()}–{end.isoformat()} "
                    "has no completed preceding stay at its location; revise the complete draft"
                )
            digest = hashlib.sha256(
                f"{day.day_id}|{start.isoformat()}".encode()
            ).hexdigest()[:20]
            block = CustomBlock(
                item_id=f"free_time_{digest}",
                day_id=day.day_id,
                title="自由休息",
                note=f"在{previous_stop.name}附近休息。",
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
