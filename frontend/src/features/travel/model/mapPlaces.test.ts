import { describe, expect, it } from 'vitest';
import { type PublicDeliveryBundle } from '../types/delivery';
import { type TransportEndpoint } from '../types/entities';
import {
  buildBundleMapPlaces,
  groupBundleMapPlaces,
  locatedBundlePlaceIds,
} from './mapPlaces';
import { buildWaypointOrder } from './waypointOrder';

function endpoint(
  name: string,
  placeId: string,
  latitude: number,
  longitude: number,
): TransportEndpoint {
  return { name, place_id: placeId, station_code: null, latitude, longitude };
}

function makeBundle(): PublicDeliveryBundle {
  const visitA = { item_id: 'visit-a', place_id: 'place-shared', name: '同点地点 A', latitude: 34.1, longitude: 108.9 };
  const visitB = { item_id: 'visit-b', place_id: 'place-shared-b', name: '同点地点 B', latitude: 34.1, longitude: 108.9 };
  const diningHydrated = { item_id: 'dining-hydrated', place_id: 'dining-endpoint', name: '由交通端点补齐的餐厅', latitude: null, longitude: null };
  const diningMissing = { item_id: 'dining-missing', place_id: 'dining-missing-place', name: '仍未定位的餐厅', latitude: null, longitude: null };
  const lodging = { stay_id: 'stay-c', place_id: 'stay-place', name: '投影中的酒店' };
  const timeline = [
    ['visit_stop', 'visit-a'],
    ['visit_stop', 'visit-b'],
    ['dining_stop', 'dining-hydrated'],
    ['dining_stop', 'dining-missing'],
    ['lodging_stay', 'stay-c'],
    ['transport_leg', 'leg-test'],
  ].map(([entity_type, entity_id], index) => ({ entry_id: `entry-${index}`, entity_type, entity_id, projection_role: 'full' }));
  const projectedB = {
    entity_ref: { entity_type: 'visit_stop', entity_id: 'visit-b' },
    name: visitB.name,
    place_id: visitB.place_id,
    latitude: visitB.latitude,
    longitude: visitB.longitude,
    citation_ids: [],
  };
  const projectedLodging = {
    entity_ref: { entity_type: 'lodging_stay', entity_id: 'stay-c' },
    name: lodging.name,
    place_id: lodging.place_id,
    latitude: 34.2,
    longitude: 108.8,
    citation_ids: [],
  };
  const sharedEndpoint = endpoint('同点地点 A', 'place-shared', 34.1, 108.9);
  const station = endpoint('独立火车站', 'station-independent', 34.3, 108.7);
  const diningEndpoint = endpoint('餐厅接驳点', 'dining-endpoint', 34.11, 108.91);
  const route = {
    entity_ref: { entity_type: 'transport_leg', entity_id: 'leg-test' },
    transport_class: 'public_transit',
    selected_mode: 'metro',
    route_status: 'ready',
    from_endpoint: sharedEndpoint,
    to_endpoint: station,
    segments: [
      { segment_id: 'segment-a', mode: 'metro', from_endpoint: sharedEndpoint, to_endpoint: station },
      { segment_id: 'segment-b', mode: 'walk', from_endpoint: diningEndpoint, to_endpoint: sharedEndpoint },
    ],
    citation_ids: [],
  };
  return {
    workspace: {
      itinerary: {
        day_plans: [{ day_id: 'day-1', day: 1, timeline }],
        visit_stops: [visitA, visitB],
        dining_stops: [diningHydrated, diningMissing],
        lodging_stays: [lodging],
        transport_legs: [],
      },
    },
    map_projection: {
      source_workspace_revision: 1,
      content: { places: [projectedB, projectedLodging], routes: [route] },
    },
  } as unknown as PublicDeliveryBundle;
}

describe('bundle map places', () => {
  it('combines itinerary and projection places and hydrates from route endpoints', () => {
    const bundle = makeBundle();
    const order = buildWaypointOrder(bundle.workspace.itinerary, locatedBundlePlaceIds(bundle));
    const places = buildBundleMapPlaces(bundle, order);

    expect(places.find((place) => place.entity_ref.entity_id === 'visit-a')).toBeDefined();
    expect(places.find((place) => place.entity_ref.entity_id === 'stay-c')).toMatchObject({
      latitude: 34.2,
      longitude: 108.8,
    });
    expect(places.find((place) => place.entity_ref.entity_id === 'dining-hydrated')).toMatchObject({
      latitude: 34.11,
      longitude: 108.91,
      days: [1],
    });
    expect(places.find((place) => place.entity_ref.entity_id === 'dining-missing')).toMatchObject({
      latitude: null,
      longitude: null,
      days: [1],
    });
  });

  it('keeps independent stations and removes endpoints already represented by places', () => {
    const bundle = makeBundle();
    const order = buildWaypointOrder(bundle.workspace.itinerary, locatedBundlePlaceIds(bundle));
    const endpoints = buildBundleMapPlaces(bundle, order).filter((place) => place.markerKind === 'transport_endpoint');

    expect(endpoints.map((place) => place.name)).toEqual(['独立火车站']);
    expect(endpoints[0]).toMatchObject({ modes: ['metro'], days: [1] });
  });

  it('groups coincident real places without hiding either entity', () => {
    const bundle = makeBundle();
    const order = buildWaypointOrder(bundle.workspace.itinerary, locatedBundlePlaceIds(bundle));
    const groups = groupBundleMapPlaces(buildBundleMapPlaces(bundle, order));
    const shared = groups.find((group) => group.places.some((place) => place.entity_ref.entity_id === 'visit-a'));

    expect(shared?.places.map((place) => place.entity_ref.entity_id)).toEqual(['visit-a', 'visit-b']);
    expect(groups.flatMap((group) => group.places).some((place) => place.entity_ref.entity_id === 'dining-missing')).toBe(false);
  });
});
