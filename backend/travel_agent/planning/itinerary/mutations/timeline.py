"""Planning itinerary mutations timeline."""

from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from travel_agent.planning.itinerary.lodging_bases import day_lodging_bases
from travel_agent.planning.itinerary.models import StructuredItineraryV2
from travel_agent.planning.itinerary.models import TimelineEntryRef
from travel_agent.planning.itinerary.mutations.contracts import WorkspaceV2MutationError
from travel_agent.planning.itinerary.mutations.derived_fields import (
    _recompute_derived_itinerary_fields,
)
from travel_agent.planning.itinerary.opening_hours import opening_window_violation
from travel_agent.planning.itinerary.time_buffers import (
    planned_alighting_buffer_minutes,
)
from travel_agent.planning.itinerary.time_buffers import planned_boarding_buffer_minutes
from travel_agent.planning.references import EntityType
from travel_agent.planning.transport import TransportEndpoint
from travel_agent.planning.workspace import TripWorkspaceV2
from typing import Optional


def _timeline_location(
    itinerary: StructuredItineraryV2, entity_id: str
) -> tuple[int, int, TimelineEntryRef]:
    matches = [
        (day_index, entry_index, ref)
        for day_index, day in enumerate(itinerary.day_plans)
        for entry_index, ref in enumerate(day.timeline)
        if ref.entity_id == entity_id
    ]
    if len(matches) != 1:
        raise WorkspaceV2MutationError(
            "timeline_item_not_unique", "Timeline item must have exactly one projection"
        )
    return matches[0]


def _move_scheduled_item_to_day(item, day):
    updates = {"day_id": day.day_id}
    if day.date is not None:
        for field in ("planned_start", "planned_end"):
            value = getattr(item, field, None)
            if value is not None:
                updates[field] = value.replace(
                    year=day.date.year,
                    month=day.date.month,
                    day=day.date.day,
                )
    return item.model_copy(update=updates)


def _drop_stale_day_notes(
    workspace: TripWorkspaceV2, itinerary: StructuredItineraryV2
) -> StructuredItineraryV2:
    """Authored daily rationale needs replanning when the day's decisions change."""
    previous = workspace.itinerary
    old_days = {day.day_id: day for day in previous.day_plans}
    old_entities = {
        item.item_id: item
        for item in [
            *previous.visit_stops,
            *previous.dining_stops,
            *previous.custom_blocks,
        ]
    }
    new_entities = {
        item.item_id: item
        for item in [
            *itinerary.visit_stops,
            *itinerary.dining_stops,
            *itinerary.custom_blocks,
        ]
    }
    old_legs = {item.transport_leg_id: item for item in previous.transport_legs}
    new_legs = {item.transport_leg_id: item for item in itinerary.transport_legs}
    prefixes = []
    for day in itinerary.day_plans:
        old = old_days.get(day.day_id)
        if (
            old is None
            or old.timeline != day.timeline
            or previous.lodging_stays != itinerary.lodging_stays
            or any(
                old_entities.get(ref.entity_id) != new_entities.get(ref.entity_id)
                or old_legs.get(ref.entity_id) != new_legs.get(ref.entity_id)
                for ref in day.timeline
            )
        ):
            prefixes.append(f"第{day.day}天安排：")
    if not prefixes:
        return itinerary
    return itinerary.model_copy(
        update={
            "important_notes": [
                note
                for note in itinerary.important_notes
                if not note.startswith(tuple(prefixes))
            ]
        }
    )


def _validate_changed_stop_windows(
    workspace: TripWorkspaceV2, itinerary: StructuredItineraryV2
) -> None:
    days = {day.day_id: day for day in itinerary.day_plans}
    previous = {
        item.item_id: item
        for item in [
            *workspace.itinerary.visit_stops,
            *workspace.itinerary.dining_stops,
            *workspace.itinerary.custom_blocks,
        ]
    }
    changed_days: set[str] = set()
    for item in [
        *itinerary.visit_stops,
        *itinerary.dining_stops,
        *itinerary.custom_blocks,
    ]:
        if item == previous.get(item.item_id):
            continue
        changed_days.add(item.day_id)
        old = previous.get(item.item_id)
        if old is not None:
            changed_days.add(old.day_id)
        day = days.get(item.day_id)
        if day is None:
            raise WorkspaceV2MutationError(
                "day_not_found", "Scheduled item day does not exist"
            )
        start, end = item.planned_start, item.planned_end
        if (start is None) != (end is None) or (
            start is not None
            and (end <= start or start.date() != day.date or end.date() != day.date)
        ):
            raise WorkspaceV2MutationError(
                "invalid_schedule", "Schedule must be ordered within its local day"
            )
        violation = opening_window_violation(
            getattr(item, "opening_window", None), day.date, start, end
        )
        if violation:
            raise WorkspaceV2MutationError(
                "opening_window_conflict",
                f"{getattr(item, 'name', getattr(item, 'title', item.item_id))}: {violation} ({getattr(item, 'opening_window', None)})",
            )
    current = {
        item.item_id: item
        for item in [
            *itinerary.visit_stops,
            *itinerary.dining_stops,
            *itinerary.custom_blocks,
        ]
    }
    transport = {item.transport_leg_id: item for item in itinerary.transport_legs}
    old_transport = {
        item.transport_leg_id: item for item in workspace.itinerary.transport_legs
    }
    for day in itinerary.day_plans:
        if day.timeline != next(
            (
                old.timeline
                for old in workspace.itinerary.day_plans
                if old.day_id == day.day_id
            ),
            [],
        ):
            changed_days.add(day.day_id)
        if any(
            transport.get(ref.entity_id) != old_transport.get(ref.entity_id)
            for ref in day.timeline
            if ref.entity_type == EntityType.TRANSPORT_LEG
        ):
            changed_days.add(day.day_id)
        if day.day_id not in changed_days:
            continue
        preceding_end: datetime | None = None
        for ref in day.timeline:
            entity = current.get(ref.entity_id)
            start = getattr(entity, "planned_start", None)
            end = getattr(entity, "planned_end", None)
            leg = (
                transport.get(ref.entity_id)
                if ref.entity_type == EntityType.TRANSPORT_LEG
                else None
            )
            if leg is not None and leg.transport_class == "long_distance":
                start, end = leg.departure_at, leg.arrival_at
                if ref.projection_role == "arrival":
                    start = end
                elif ref.projection_role == "departure":
                    end = start
            if start is None or end is None:
                continue
            if preceding_end is not None and start < preceding_end:
                raise WorkspaceV2MutationError(
                    "schedule_overlap",
                    "Changed schedule overlaps another activity or fixed transport",
                )
            preceding_end = end


def _boundary_for_ref(
    itinerary: StructuredItineraryV2, ref: TimelineEntryRef, *, previous: bool
) -> tuple[Optional[TransportEndpoint], Optional[datetime]]:
    collections = {
        EntityType.VISIT_STOP: (itinerary.visit_stops, "item_id"),
        EntityType.DINING_STOP: (itinerary.dining_stops, "item_id"),
        EntityType.LODGING_STAY: (itinerary.lodging_stays, "stay_id"),
    }
    target = collections.get(ref.entity_type)
    if ref.entity_type == EntityType.TRANSPORT_LEG:
        leg = next(
            (
                item
                for item in itinerary.transport_legs
                if item.transport_leg_id == ref.entity_id
            ),
            None,
        )
        if leg is not None and leg.transport_class == "long_distance":
            return (
                (
                    leg.to_endpoint,
                    leg.arrival_at
                    + timedelta(
                        minutes=planned_alighting_buffer_minutes(leg.selected_mode)
                    )
                    if leg.arrival_at is not None
                    else None,
                )
                if previous
                else (
                    leg.from_endpoint,
                    leg.departure_at
                    - timedelta(
                        minutes=planned_boarding_buffer_minutes(leg.selected_mode)
                    )
                    if leg.departure_at is not None
                    else None,
                )
            )
    if target is None:
        return None, None
    items, identity = target
    entity = next(
        (item for item in items if getattr(item, identity) == ref.entity_id), None
    )
    if entity is None:
        return None, None
    return TransportEndpoint(name=entity.name, place_id=entity.place_id), getattr(
        entity, "planned_end" if previous else "planned_start", None
    )


def _invalidate_changed_connectors(
    itinerary: StructuredItineraryV2,
) -> StructuredItineraryV2:
    legs = {leg.transport_leg_id: leg for leg in itinerary.transport_legs}
    for day in itinerary.day_plans:
        morning_base, evening_base = day_lodging_bases(itinerary, day)
        for index, ref in enumerate(day.timeline):
            if ref.entity_type != EntityType.TRANSPORT_LEG:
                continue
            leg = legs[ref.entity_id]
            if leg.transport_class == "long_distance":
                continue
            previous = next(
                (
                    boundary
                    for item in reversed(day.timeline[:index])
                    if (boundary := _boundary_for_ref(itinerary, item, previous=True))[
                        0
                    ]
                    is not None
                ),
                (None, None),
            )
            following = next(
                (
                    boundary
                    for item in day.timeline[index + 1 :]
                    if (boundary := _boundary_for_ref(itinerary, item, previous=False))[
                        0
                    ]
                    is not None
                ),
                (None, None),
            )
            from_endpoint, departure = previous
            to_endpoint, arrival_limit = following
            if from_endpoint is None and morning_base is not None:
                from_endpoint = TransportEndpoint(
                    name=morning_base.name, place_id=morning_base.place_id
                )
                if arrival_limit is not None:
                    departure = max(
                        arrival_limit.replace(
                            hour=0, minute=0, second=0, microsecond=0
                        ),
                        arrival_limit - timedelta(minutes=90),
                    )
            if to_endpoint is None and evening_base is not None:
                to_endpoint = TransportEndpoint(
                    name=evening_base.name, place_id=evening_base.place_id
                )
                if departure is not None:
                    arrival_limit = min(
                        departure.replace(hour=23, minute=59, second=0, microsecond=0),
                        departure + timedelta(minutes=90),
                    )
            if from_endpoint is None or to_endpoint is None:
                continue
            same_endpoints = (
                from_endpoint.place_id == leg.from_endpoint.place_id
                and to_endpoint.place_id == leg.to_endpoint.place_id
                and (
                    from_endpoint.place_id is not None
                    or from_endpoint == leg.from_endpoint
                )
                and (to_endpoint.place_id is not None or to_endpoint == leg.to_endpoint)
            )
            times_fit = True
            if departure is not None and arrival_limit is not None:
                blocks = [
                    block
                    for block in itinerary.custom_blocks
                    if block.day_id == day.day_id
                    and block.planned_start is not None
                    and block.planned_end is not None
                ]
                if leg.departure_at is not None and leg.arrival_at is not None:
                    times_fit = (
                        leg.departure_at >= departure
                        and leg.arrival_at <= arrival_limit
                        and not any(
                            block.planned_start < leg.arrival_at
                            and block.planned_end > leg.departure_at
                            for block in blocks
                        )
                    )
                elif leg.duration_minutes is not None:
                    reserved = sum(
                        (
                            max(
                                timedelta(),
                                min(block.planned_end, arrival_limit)
                                - max(block.planned_start, departure),
                            )
                            for block in blocks
                        ),
                        timedelta(),
                    )
                    times_fit = (
                        departure + timedelta(minutes=leg.duration_minutes) + reserved
                        <= arrival_limit
                    )
            if same_endpoints and times_fit:
                continue
            legs[ref.entity_id] = leg.model_copy(
                update={
                    "from_endpoint": from_endpoint,
                    "to_endpoint": to_endpoint,
                    "departure_at": None,
                    "arrival_at": None,
                    "segments": [],
                    "transfer_count": 0,
                    "route_status": "pending",
                    "duration_minutes": None,
                    "distance_meters": None,
                    "total_cost_cny": None,
                }
            )
    return _recompute_derived_itinerary_fields(
        itinerary.model_copy(update={"transport_legs": list(legs.values())})
    )
