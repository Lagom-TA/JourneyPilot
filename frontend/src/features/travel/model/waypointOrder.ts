import { type MapProjection } from "../types/report";
import { type PublicStructuredItineraryV2 } from "../types/itinerary";
export interface WaypointPlacement {
    sequence: number;
    days: number[];
}
const PHYSICAL_ENTITY_TYPES = ['visit_stop', 'dining_stop', 'lodging_stay'] as const;
export function isPhysicalPlaceEntityType(entityType: string): boolean {
    return (PHYSICAL_ENTITY_TYPES as readonly string[]).includes(entityType);
}
export function pinnedMapPlaceIds(places: readonly MapProjection['content']['places'][number][]): string[] {
    return places
        .filter((place) => (isPhysicalPlaceEntityType(place.entity_ref.entity_type)
        && place.latitude != null
        && place.longitude != null))
        .map((place) => place.entity_ref.entity_id);
}
export function buildWaypointOrder(itinerary: PublicStructuredItineraryV2, mapPlaceIds: readonly string[] = []): Map<string, WaypointPlacement> {
    const pinned = new Set(mapPlaceIds);
    const order = new Map<string, WaypointPlacement>();
    let sequence = 1;
    for (const day of itinerary.day_plans) {
        for (const entry of day.timeline) {
            if (!isPhysicalPlaceEntityType(entry.entity_type))
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
