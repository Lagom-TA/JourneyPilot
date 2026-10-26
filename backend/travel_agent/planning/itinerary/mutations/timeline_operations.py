from __future__ import annotations

from travel_agent.planning.itinerary.models import TimelineEntryRef
from travel_agent.planning.itinerary.mutations.contracts import (
    CreateCustomBlockMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import (
    DeleteCustomBlockMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import MoveTimelineItemMutation
from travel_agent.planning.itinerary.mutations.contracts import (
    UpdateCustomBlockMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import (
    UpdateStopScheduleMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import (
    WorkspaceV2MutationApplication,
)
from travel_agent.planning.itinerary.mutations.contracts import WorkspaceV2MutationError
from travel_agent.planning.itinerary.mutations.results import _itinerary_result
from travel_agent.planning.itinerary.mutations.timeline import (
    _invalidate_changed_connectors,
)
from travel_agent.planning.itinerary.mutations.timeline import (
    _move_scheduled_item_to_day,
)
from travel_agent.planning.itinerary.mutations.timeline import _timeline_location
from travel_agent.planning.references import EntityType
from travel_agent.planning.workspace import TripWorkspaceV2


def apply_move_timeline_item(
    workspace: TripWorkspaceV2, mutation: MoveTimelineItemMutation
) -> WorkspaceV2MutationApplication:
    itinerary = workspace.itinerary
    source_day, source_index, ref = _timeline_location(itinerary, mutation.item_id)
    if ref.entity_type not in {
        EntityType.VISIT_STOP,
        EntityType.DINING_STOP,
        EntityType.CUSTOM_BLOCK,
    }:
        raise WorkspaceV2MutationError(
            "item_not_movable", "Only Visit, Dining, and Custom items can be moved"
        )
    target_day = next(
        (
            index
            for index, day in enumerate(itinerary.day_plans)
            if day.day_id == mutation.to_day_id
        ),
        None,
    )
    if target_day is None:
        raise WorkspaceV2MutationError("day_not_found", "Target day does not exist")
    day_plans = [day.model_copy(deep=True) for day in itinerary.day_plans]
    moved = day_plans[source_day].timeline.pop(source_index)
    target_timeline = day_plans[target_day].timeline
    if mutation.before_entry_id is None:
        target_timeline.append(moved)
    else:
        before = next(
            (
                index
                for index, item in enumerate(target_timeline)
                if item.entry_id == mutation.before_entry_id
            ),
            None,
        )
        if before is None:
            raise WorkspaceV2MutationError(
                "before_entry_not_found",
                "Insertion anchor does not exist in target day",
            )
        target_timeline.insert(before, moved)
    updates = {"day_plans": day_plans}
    key = {
        EntityType.VISIT_STOP: "visit_stops",
        EntityType.DINING_STOP: "dining_stops",
        EntityType.CUSTOM_BLOCK: "custom_blocks",
    }[ref.entity_type]
    target = day_plans[target_day]
    updates[key] = [
        _move_scheduled_item_to_day(item, target)
        if item.item_id == ref.entity_id
        else item
        for item in getattr(itinerary, key)
    ]
    next_itinerary = _invalidate_changed_connectors(
        itinerary.model_copy(update=updates)
    )
    return _itinerary_result(workspace, next_itinerary, "移动行程安排")


def apply_update_stop_schedule(
    workspace: TripWorkspaceV2, mutation: UpdateStopScheduleMutation
) -> WorkspaceV2MutationApplication:
    itinerary = workspace.itinerary
    for key in ("visit_stops", "dining_stops", "custom_blocks"):
        items = getattr(itinerary, key)
        current = next(
            (item for item in items if item.item_id == mutation.item_id), None
        )
        if current is None:
            continue
        values = {
            name: getattr(mutation, name)
            for name in ("planned_start", "planned_end", "duration_minutes")
            if name in mutation.model_fields_set
        }
        updated = current.model_copy(update=values)
        if (
            updated.planned_start
            and updated.planned_end
            and updated.planned_end <= updated.planned_start
        ):
            raise WorkspaceV2MutationError(
                "invalid_schedule", "planned_end must be after planned_start"
            )
        return _itinerary_result(
            workspace,
            itinerary.model_copy(
                update={
                    key: [
                        updated if item.item_id == current.item_id else item
                        for item in items
                    ]
                }
            ),
            "调整时间",
        )
    raise WorkspaceV2MutationError(
        "scheduled_item_not_found", "Scheduled item does not exist"
    )


def apply_create_custom_block(
    workspace: TripWorkspaceV2, mutation: CreateCustomBlockMutation
) -> WorkspaceV2MutationApplication:
    itinerary = workspace.itinerary
    if mutation.block.day_id not in {day.day_id for day in itinerary.day_plans}:
        raise WorkspaceV2MutationError(
            "day_not_found", "Custom block day does not exist"
        )
    if any(item.item_id == mutation.block.item_id for item in itinerary.custom_blocks):
        raise WorkspaceV2MutationError(
            "item_id_conflict", "Custom block id already exists"
        )
    day_plans = [day.model_copy(deep=True) for day in itinerary.day_plans]
    day = next(item for item in day_plans if item.day_id == mutation.block.day_id)
    ref = TimelineEntryRef(
        entry_id=f"entry_{mutation.block.item_id}",
        entity_type=EntityType.CUSTOM_BLOCK,
        entity_id=mutation.block.item_id,
    )
    if mutation.before_entry_id is None:
        day.timeline.append(ref)
    else:
        before = next(
            (
                i
                for i, item in enumerate(day.timeline)
                if item.entry_id == mutation.before_entry_id
            ),
            None,
        )
        if before is None:
            raise WorkspaceV2MutationError(
                "before_entry_not_found", "Insertion anchor does not exist"
            )
        day.timeline.insert(before, ref)
    return _itinerary_result(
        workspace,
        itinerary.model_copy(
            update={
                "day_plans": day_plans,
                "custom_blocks": [*itinerary.custom_blocks, mutation.block],
            }
        ),
        f"添加{mutation.block.title}",
    )


def apply_update_custom_block(
    workspace: TripWorkspaceV2, mutation: UpdateCustomBlockMutation
) -> WorkspaceV2MutationApplication:
    itinerary = workspace.itinerary
    current = next(
        (item for item in itinerary.custom_blocks if item.item_id == mutation.item_id),
        None,
    )
    if current is None:
        raise WorkspaceV2MutationError(
            "custom_block_not_found", "Custom block does not exist"
        )
    values = {
        name: getattr(mutation, name)
        for name in (
            "title",
            "note",
            "planned_start",
            "planned_end",
            "duration_minutes",
        )
        if name in mutation.model_fields_set
    }
    updated = current.model_copy(update=values)
    if (
        updated.planned_start
        and updated.planned_end
        and updated.planned_end <= updated.planned_start
    ):
        raise WorkspaceV2MutationError(
            "invalid_schedule", "planned_end must be after planned_start"
        )
    return _itinerary_result(
        workspace,
        itinerary.model_copy(
            update={
                "custom_blocks": [
                    updated if item.item_id == current.item_id else item
                    for item in itinerary.custom_blocks
                ]
            }
        ),
        f"更新{updated.title}",
    )


def apply_delete_custom_block(
    workspace: TripWorkspaceV2, mutation: DeleteCustomBlockMutation
) -> WorkspaceV2MutationApplication:
    itinerary = workspace.itinerary
    if not any(item.item_id == mutation.item_id for item in itinerary.custom_blocks):
        raise WorkspaceV2MutationError(
            "custom_block_not_found", "Custom block does not exist"
        )
    day_plans = [
        day.model_copy(
            update={
                "timeline": [
                    ref
                    for ref in day.timeline
                    if not (
                        ref.entity_type == EntityType.CUSTOM_BLOCK
                        and ref.entity_id == mutation.item_id
                    )
                ]
            }
        )
        for day in itinerary.day_plans
    ]
    return _itinerary_result(
        workspace,
        itinerary.model_copy(
            update={
                "day_plans": day_plans,
                "custom_blocks": [
                    item
                    for item in itinerary.custom_blocks
                    if item.item_id != mutation.item_id
                ],
            }
        ),
        "删除自定义安排",
    )
