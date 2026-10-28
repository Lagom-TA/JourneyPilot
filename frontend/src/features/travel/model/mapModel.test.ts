import { describe, expect, it } from 'vitest';
import { type TransportEndpoint, type TransportSegment } from '../types/entities';
import { type MapProjection } from '../types/report';
import {
  mapViewportDataKey,
  resolveMapFocusEntityId,
  routeLines,
  shouldAutoFitMap,
} from './mapModel';
import { pointOnTileDatum } from './tileDatum';

type ProjectedRoute = MapProjection['content']['routes'][number];

const SHANGHAI = { latitude: 31.2304, longitude: 121.4737 };
const HANGZHOU = { latitude: 30.2741, longitude: 120.1551 };
const SUZHOU = { latitude: 31.2989, longitude: 120.5853 };

function endpoint(latitude: number | null, longitude: number | null): TransportEndpoint {
  return {
    name: 'test endpoint',
    place_id: null,
    station_code: null,
    latitude,
    longitude,
  };
}

function segment(overrides: Partial<TransportSegment> = {}): TransportSegment {
  return {
    segment_id: 'segment-1',
    mode: 'train',
    from_endpoint: endpoint(SHANGHAI.latitude, SHANGHAI.longitude),
    to_endpoint: endpoint(HANGZHOU.latitude, HANGZHOU.longitude),
    departure_at: null,
    arrival_at: null,
    duration_minutes: null,
    distance_meters: null,
    operator_name: null,
    service_number: null,
    line_name: null,
    cost_cny: null,
    ...overrides,
  };
}

function route(overrides: Partial<ProjectedRoute> = {}): ProjectedRoute {
  return {
    entity_ref: { entity_type: 'transport_leg', entity_id: 'route-1' },
    transport_class: 'long_distance',
    selected_mode: 'train',
    route_status: 'ready',
    from_endpoint: endpoint(SHANGHAI.latitude, SHANGHAI.longitude),
    to_endpoint: endpoint(HANGZHOU.latitude, HANGZHOU.longitude),
    segments: [segment()],
    citation_ids: [],
    ...overrides,
  };
}

describe('map route geometry', () => {
  it('uses every provider path point and preserves segment identity', () => {
    const path = [SHANGHAI, SUZHOU, HANGZHOU];
    const lines = routeLines(route({
      segments: [segment({
        path,
        from_endpoint: endpoint(null, null),
        to_endpoint: endpoint(null, null),
      })],
    }));

    expect(lines).toEqual([{
      segmentId: 'segment-1',
      mode: 'train',
      geometryKind: 'provider',
      points: path.map((point) => pointOnTileDatum(point)!),
    }]);
  });

  it('falls back to real segment endpoints when path is absent', () => {
    expect(routeLines(route())).toEqual([{
      segmentId: 'segment-1',
      mode: 'train',
      geometryKind: 'endpoint',
      points: [
        pointOnTileDatum(SHANGHAI)!,
        pointOnTileDatum(HANGZHOU)!,
      ],
    }]);
  });

  it('always uses a two-point direct line for a flight', () => {
    const lines = routeLines(route({
      selected_mode: 'flight',
      segments: [segment({
        mode: 'flight',
        path: [SHANGHAI, SUZHOU, HANGZHOU],
      })],
    }));

    expect(lines).toEqual([{
      segmentId: 'segment-1',
      mode: 'flight',
      geometryKind: 'direct',
      points: [
        pointOnTileDatum(SHANGHAI)!,
        pointOnTileDatum(HANGZHOU)!,
      ],
    }]);
  });

  it('keeps mode and geometry independent across transfer segments', () => {
    const lines = routeLines(route({
      transport_class: 'public_transit',
      selected_mode: 'metro',
      segments: [
        segment({ segment_id: 'walk-to-station', mode: 'walk' }),
        segment({ segment_id: 'metro-line', mode: 'metro', path: [SHANGHAI, SUZHOU, HANGZHOU] }),
      ],
    }));

    expect(lines.map((line) => [line.segmentId, line.mode, line.geometryKind])).toEqual([
      ['walk-to-station', 'walk', 'endpoint'],
      ['metro-line', 'metro', 'provider'],
    ]);
  });

  it.each(['taxi', 'ride_hailing'] as const)('uses the %s display color for a provider drive path', (selectedMode) => {
    const lines = routeLines(route({
      transport_class: 'flexible',
      selected_mode: selectedMode,
      segments: [segment({ mode: 'drive', path: [SHANGHAI, SUZHOU, HANGZHOU] })],
    }));

    expect(lines[0]).toMatchObject({ mode: selectedMode, geometryKind: 'provider' });
    expect(lines[0].points).toHaveLength(3);
  });

  it('treats a one-point path as invalid and falls back to endpoints', () => {
    const lines = routeLines(route({ segments: [segment({ path: [SHANGHAI] })] }));

    expect(lines).toEqual([{
      segmentId: 'segment-1',
      mode: 'train',
      geometryKind: 'endpoint',
      points: [
        pointOnTileDatum(SHANGHAI)!,
        pointOnTileDatum(HANGZHOU)!,
      ],
    }]);
  });

  it('skips only endpoint fallback segments with missing coordinates', () => {
    const missing = segment({
      segment_id: 'missing-coordinates',
      from_endpoint: endpoint(null, SHANGHAI.longitude),
    });
    const drawable = segment({ segment_id: 'drawable' });

    expect(routeLines(route({ segments: [missing, drawable] }))).toEqual([{
      segmentId: 'drawable',
      mode: 'train',
      geometryKind: 'endpoint',
      points: [
        pointOnTileDatum(SHANGHAI)!,
        pointOnTileDatum(HANGZHOU)!,
      ],
    }]);
  });

  it.each(['pending', 'unavailable'] as const)('does not draw %s routes', (routeStatus) => {
    expect(routeLines(route({
      route_status: routeStatus,
      segments: [segment({ path: [SHANGHAI, HANGZHOU] })],
    }))).toEqual([]);
  });
});

describe('map viewport focus', () => {
  it('prioritizes the selected entity over the linked entity', () => {
    expect(resolveMapFocusEntityId('selected-place', 'linked-place')).toBe('selected-place');
  });

  it('uses the linked entity when there is no selection', () => {
    expect(resolveMapFocusEntityId(null, 'linked-place')).toBe('linked-place');
  });

  it('clears the focus when selection and hover are both cleared', () => {
    expect(resolveMapFocusEntityId(null, null)).toBeNull();
  });

  it('does not fit the whole map when hover clears without a data change', () => {
    const dataKey = mapViewportDataKey([[31.2304, 121.4737]]);

    expect(shouldAutoFitMap({
      dataKey,
      previousDataKey: dataKey,
      hasFocusTarget: false,
    })).toBe(false);
  });

  it('fits initially or after real geometry changes only when nothing is focused', () => {
    const dataKey = mapViewportDataKey([[31.2304, 121.4737]]);

    expect(shouldAutoFitMap({ dataKey, previousDataKey: null, hasFocusTarget: false })).toBe(true);
    expect(shouldAutoFitMap({ dataKey, previousDataKey: 'older-data', hasFocusTarget: false })).toBe(true);
    expect(shouldAutoFitMap({ dataKey, previousDataKey: 'older-data', hasFocusTarget: true })).toBe(false);
  });

  it('keys viewport data by geometry rather than array identity', () => {
    const first = mapViewportDataKey([[31.2304, 121.4737]]);
    const sameGeometry = mapViewportDataKey([[31.2304, 121.4737]]);
    const changedGeometry = mapViewportDataKey([[30.2741, 120.1551]]);

    expect(sameGeometry).toBe(first);
    expect(changedGeometry).not.toBe(first);
  });
});
