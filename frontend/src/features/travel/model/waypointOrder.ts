import { type PublicStructuredItineraryV2 } from "../types/itinerary";
export interface WaypointPlacement {
    sequence: number;
    days: number[];
}
export function buildWaypointOrder(itinerary: PublicStructuredItineraryV2, mapPlaceIds: readonly string[] = []): Map<string, WaypointPlacement> {
    const pinned = new Set(mapPlaceIds);
    const PHYSICAL_ENTITY_TYPES = ['visit_stop', 'dining_stop', 'lodging_stay'] as const;
    const isPhysical = (entityType: string): boolean =>
        (PHYSICAL_ENTITY_TYPES as readonly string[]).includes(entityType);
    const order = new Map<string, WaypointPlacement>();
    let sequence = 1;
    for (const day of itinerary.day_plans) {
        for (const entry of day.timeline) {
            if (!isPhysical(entry.entity_type))
                continue;
            if (!pinned.has(entry.entity_id))
                continue;
            const current = order.get(entry.entity_id);
            if (!current)
                order.set(entry.entity_id, { days: [day.day], sequence: sequence++ });
            else if (!current.days.includes(day.day))
                current.days.push(day.day);
        }
    }
    for (const placeId of mapPlaceIds) {
        if (!order.has(placeId))
            order.set(placeId, { days: [], sequence: sequence++ });
    }
    return order;
}
const PINNED_ENTITY_KINDS = new Set(['visit', 'dining', 'lodging']);
export function waypointSequenceFor(order: ReadonlyMap<string, WaypointPlacement>, entityKind: string, entityId: string): number | null {
    if (!PINNED_ENTITY_KINDS.has(entityKind))
        return null;
    return order.get(entityId)?.sequence ?? null;
}
