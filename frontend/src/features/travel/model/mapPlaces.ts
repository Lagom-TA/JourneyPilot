import { type PublicDeliveryBundle } from '../types/delivery';
import { type TransportEndpoint, type TransportMode } from '../types/entities';
import { type MapProjection } from '../types/report';
import { type WaypointPlacement } from './waypointOrder';
import { transportSegmentDisplayMode } from './transportPresentation';

type ProjectedPlace = MapProjection['content']['places'][number];
type ProjectedRoute = MapProjection['content']['routes'][number];

export type BundleMapMarkerKind = 'place' | 'identity' | 'transport_endpoint';

export interface BundleMapPlace extends ProjectedPlace {
  days: number[];
  sequence: number;
  markerId: string;
  markerKind: BundleMapMarkerKind;
  modes: TransportMode[];
}

export interface BundleMapPlaceGroup {
  id: string;
  places: BundleMapPlace[];
}

type PhysicalPlaceRecord = {
  entityRef: ProjectedPlace['entity_ref'];
  name: string;
  placeId: string;
  latitude: number | null;
  longitude: number | null;
};

function validCoordinate(latitude: number | null | undefined, longitude: number | null | undefined): boolean {
  return typeof latitude === 'number' && Number.isFinite(latitude)
    && typeof longitude === 'number' && Number.isFinite(longitude);
}

export function isLocatedBundleMapPlace(place: BundleMapPlace): boolean {
  return validCoordinate(place.latitude, place.longitude);
}

function physicalPlaceRecords(bundle: PublicDeliveryBundle): PhysicalPlaceRecord[] {
  const { itinerary } = bundle.workspace;
  return [
    ...itinerary.visit_stops.map((place) => ({
      entityRef: { entity_type: 'visit_stop' as const, entity_id: place.item_id },
      name: place.name,
      placeId: place.place_id,
      latitude: place.latitude,
      longitude: place.longitude,
    })),
    ...itinerary.dining_stops.map((place) => ({
      entityRef: { entity_type: 'dining_stop' as const, entity_id: place.item_id },
      name: place.name,
      placeId: place.place_id,
      latitude: place.latitude,
      longitude: place.longitude,
    })),
    ...itinerary.lodging_stays.map((place) => ({
      entityRef: { entity_type: 'lodging_stay' as const, entity_id: place.stay_id },
      name: place.name,
      placeId: place.place_id,
      latitude: null,
      longitude: null,
    })),
  ];
}

export function locatedBundlePlaceIds(bundle: PublicDeliveryBundle): string[] {
  const ids = new Set<string>();
  for (const place of bundle.map_projection.content.places) {
    if (validCoordinate(place.latitude, place.longitude)) ids.add(place.entity_ref.entity_id);
  }
  for (const place of physicalPlaceRecords(bundle)) {
    if (validCoordinate(place.latitude, place.longitude)) ids.add(place.entityRef.entity_id);
  }
  const locatedEndpoints = transportEndpointPlaces(bundle.map_projection.content.routes, new Map());
  const endpointByPlaceId = new Map(locatedEndpoints.map((place) => [place.place_id, place]));
  for (const place of physicalPlaceRecords(bundle)) {
    if (endpointByPlaceId.has(place.placeId)) ids.add(place.entityRef.entity_id);
  }
  return [...ids];
}

function scheduledEntityDays(bundle: PublicDeliveryBundle): Map<string, number[]> {
  const days = new Map<string, number[]>();
  for (const day of bundle.workspace.itinerary.day_plans) {
    for (const entry of day.timeline) {
      const entityDays = days.get(entry.entity_id) ?? [];
      if (!entityDays.includes(day.day)) entityDays.push(day.day);
      days.set(entry.entity_id, entityDays);
    }
  }
  return days;
}

function endpointKey(endpoint: TransportEndpoint): string | null {
  if (!validCoordinate(endpoint.latitude, endpoint.longitude)) return null;
  return endpoint.place_id || `${endpoint.latitude!.toFixed(6)},${endpoint.longitude!.toFixed(6)}`;
}

function transportEndpointPlaces(
  routes: ProjectedRoute[],
  daysByRoute: ReadonlyMap<string, number[]>,
): BundleMapPlace[] {
  const endpoints = new Map<string, BundleMapPlace>();
  for (const route of routes) {
    if (route.route_status !== 'ready') continue;
    const routeId = route.entity_ref.entity_id;
    for (const segment of route.segments) {
      const mode = transportSegmentDisplayMode(route.selected_mode, segment.mode);
      for (const endpoint of [segment.from_endpoint, segment.to_endpoint]) {
        const key = endpointKey(endpoint);
        if (!key) continue;
        const existing = endpoints.get(key);
        const days = daysByRoute.get(routeId) ?? [];
        if (existing) {
          existing.days = [...new Set([...existing.days, ...days])].sort((a, b) => a - b);
          if (!existing.modes.includes(mode)) existing.modes.push(mode);
          continue;
        }
        endpoints.set(key, {
          entity_ref: route.entity_ref,
          name: endpoint.name,
          place_id: endpoint.place_id ?? key,
          latitude: endpoint.latitude,
          longitude: endpoint.longitude,
          citation_ids: route.citation_ids,
          days: [...days],
          sequence: 0,
          markerId: `endpoint:${key}`,
          markerKind: 'transport_endpoint',
          modes: [mode],
        });
      }
    }
  }
  return [...endpoints.values()];
}

export function buildBundleMapPlaces(
  bundle: PublicDeliveryBundle,
  waypointOrder: ReadonlyMap<string, WaypointPlacement>,
): BundleMapPlace[] {
  const projected = new Map(
    bundle.map_projection.content.places.map((place) => [place.entity_ref.entity_id, place]),
  );
  const records = physicalPlaceRecords(bundle);
  const recordIds = new Set(records.map((record) => record.entityRef.entity_id));
  for (const place of bundle.map_projection.content.places) {
    if (recordIds.has(place.entity_ref.entity_id)) continue;
    records.push({
      entityRef: place.entity_ref,
      name: place.name,
      placeId: place.place_id,
      latitude: place.latitude,
      longitude: place.longitude,
    });
  }

  const daysByEntity = scheduledEntityDays(bundle);
  const places = records.map((record): BundleMapPlace => {
    const entityId = record.entityRef.entity_id;
    const projection = projected.get(entityId);
    const order = waypointOrder.get(entityId);
    return {
      entity_ref: record.entityRef,
      name: projection?.name ?? record.name,
      place_id: projection?.place_id ?? record.placeId,
      latitude: projection?.latitude ?? record.latitude,
      longitude: projection?.longitude ?? record.longitude,
      citation_ids: projection?.citation_ids ?? [],
      days: order?.days ?? daysByEntity.get(entityId) ?? [],
      sequence: order?.sequence ?? 0,
      markerId: `place:${entityId}`,
      markerKind: 'place',
      modes: [],
    };
  });
  const endpoints = transportEndpointPlaces(bundle.map_projection.content.routes, daysByEntity);
  const endpointByPlaceId = new Map(endpoints.map((place) => [place.place_id, place]));
  const hydratedPlaces = places.map((place) => {
    if (isLocatedBundleMapPlace(place)) return place;
    const endpoint = endpointByPlaceId.get(place.place_id);
    if (!endpoint) return place;
    return { ...place, latitude: endpoint.latitude, longitude: endpoint.longitude };
  });
  const occupiedPlaces = new Set(
    hydratedPlaces.filter(isLocatedBundleMapPlace).map((place) => (
      `${place.latitude!.toFixed(6)},${place.longitude!.toFixed(6)}`
    )),
  );
  const distinctEndpoints = endpoints.filter((place) => (
    !occupiedPlaces.has(`${place.latitude!.toFixed(6)},${place.longitude!.toFixed(6)}`)
  ));
  return [...hydratedPlaces, ...distinctEndpoints];
}

export function groupBundleMapPlaces(places: BundleMapPlace[]): BundleMapPlaceGroup[] {
  const groups = new Map<string, BundleMapPlace[]>();
  for (const place of places) {
    if (!isLocatedBundleMapPlace(place)) continue;
    const key = `${place.latitude!.toFixed(6)},${place.longitude!.toFixed(6)}`;
    groups.set(key, [...(groups.get(key) ?? []), place]);
  }
  return [...groups.entries()].map(([key, groupedPlaces]) => ({
    id: `group:${key}`,
    places: groupedPlaces,
  }));
}
