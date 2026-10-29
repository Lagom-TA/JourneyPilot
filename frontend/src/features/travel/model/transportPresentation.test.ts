import { describe, expect, it } from 'vitest';
import { type TransportMode } from '../types/entities';
import { type PublicTransportLeg } from '../types/itinerary';
import {
  TRANSPORT_MODE_COLORS,
  confirmedMetroTransferCount,
  legSummary,
  showsEndpointCode,
  transitDisplayMode,
  transitModeLabel,
  transitRideModes,
  transitStationModes,
  transitStations,
  transportModeColor,
  transportModeStyle,
  transportRouteActionVisible,
  transportSegmentDisplayMode,
} from './transportPresentation';

function endpoint(name: string, stationCode: string | null = null) {
  return { name, place_id: `place:${name}`, station_code: stationCode, latitude: null, longitude: null };
}

function segment(id: string, mode: TransportMode, from: string, to: string, lineName: string | null = null) {
  return {
    segment_id: id,
    mode,
    from_endpoint: endpoint(from),
    to_endpoint: endpoint(to),
    departure_at: null,
    arrival_at: null,
    duration_minutes: null,
    distance_meters: null,
    operator_name: null,
    service_number: null,
    line_name: lineName,
    cost_cny: null,
    path: [],
  };
}

function transportLeg(overrides: Partial<PublicTransportLeg> = {}): PublicTransportLeg {
  return {
    type: 'transport_leg',
    transport_leg_id: 'leg-test',
    transport_class: 'public_transit',
    selected_mode: 'metro',
    from_endpoint: endpoint('西安钟楼饭店'),
    to_endpoint: endpoint('陕西历史博物馆'),
    boarding_stop: null,
    alighting_stop: null,
    departure_at: null,
    arrival_at: null,
    duration_minutes: 42,
    distance_meters: 5800,
    total_cost_cny: 5,
    transfer_count: 0,
    segments: [segment('walk-in', 'walk', '西安钟楼饭店', '钟楼站')],
    booking_status: 'not_required',
    route_status: 'ready',
    mode_preference: { locked_mode: null, excluded_modes: [] },
    intent_explanations: [],
    evidence_basis: 'public_reference',
    is_micro_transport: false,
    ...overrides,
  };
}

const walkMetroWalk = [
  segment('walk-in', 'walk', '西安钟楼饭店', '钟楼站'),
  segment('metro-2', 'metro', '钟楼站', '小寨站', '地铁2号线'),
  segment('walk-out', 'walk', '小寨站', '陕西历史博物馆'),
];

const MODES: TransportMode[] = [
  'flight',
  'high_speed_rail',
  'train',
  'coach',
  'ferry',
  'metro',
  'bus',
  'tram',
  'taxi',
  'ride_hailing',
  'drive',
  'bike',
  'walk',
  'other',
];

describe('transport mode colors', () => {
  it('provides a distinct color for every transport mode', () => {
    expect(MODES.map((mode) => TRANSPORT_MODE_COLORS[mode])).toHaveLength(MODES.length);
    expect(new Set(Object.values(TRANSPORT_MODE_COLORS)).size).toBe(MODES.length);
    for (const mode of MODES) {
      expect(TRANSPORT_MODE_COLORS[mode]).toMatch(/^#[0-9A-F]{6}$/);
    }
  });

  it('uses the same color for map lines and component styles', () => {
    for (const mode of MODES) {
      expect(transportModeStyle(mode)).toEqual({
        '--transport-mode-color': transportModeColor(mode),
      });
    }
  });

  it('keeps road service display modes without changing other segment modes', () => {
    expect(transportSegmentDisplayMode('taxi', 'drive')).toBe('taxi');
    expect(transportSegmentDisplayMode('ride_hailing', 'drive')).toBe('ride_hailing');
    expect(transportSegmentDisplayMode('drive', 'drive')).toBe('drive');
    expect(transportSegmentDisplayMode('taxi', 'walk')).toBe('walk');
  });
});

describe('transport card facts', () => {
  it('summarises a scheduled ticket as plain duration and fare', () => {
    const summary = legSummary(transportLeg({
      transport_class: 'long_distance',
      selected_mode: 'high_speed_rail',
      duration_minutes: 469,
      total_cost_cny: 1108,
      segments: [segment('rail', 'high_speed_rail', '深圳北', '北京西', null)],
    }));
    expect(summary).toEqual({ duration: '7 小时 49 分钟', transfer: null, cost: '¥1,108' });
  });

  it('does not invent a zero fare when the price is missing', () => {
    const summary = legSummary(transportLeg({ total_cost_cny: null }));
    expect(summary.duration).toBe('42 分钟');
    expect(summary.cost).toBeNull();
  });

  it('hides a zero transfer instead of writing direct', () => {
    expect(confirmedMetroTransferCount(transportLeg({ segments: walkMetroWalk, transfer_count: 0 }))).toBe(0);
    expect(legSummary(transportLeg({ segments: walkMetroWalk, transfer_count: 0 })).transfer).toBeNull();
  });

  it('counts only a real change between metro lines', () => {
    const sameLineSplit = [
      segment('metro-2a', 'metro', '钟楼站', '北大街站', '地铁2号线'),
      segment('metro-2b', 'metro', '北大街站', '小寨站', '地铁2号线'),
    ];
    expect(confirmedMetroTransferCount(transportLeg({ segments: sameLineSplit, transfer_count: 0 }))).toBe(0);
    const twoLines = [
      segment('metro-2', 'metro', '北大街站', '行政中心站', '地铁2号线'),
      segment('metro-4', 'metro', '行政中心站', '大雁塔站', '地铁4号线'),
    ];
    expect(confirmedMetroTransferCount(transportLeg({ segments: twoLines, transfer_count: 1 }))).toBe(1);
    expect(legSummary(transportLeg({ segments: twoLines, transfer_count: 1 })).transfer).toBe('换乘 1 次');
  });

  it('does not read a mixed bus service count as a metro transfer', () => {
    const mixed = [
      segment('bus', 'bus', '钟楼站', '小寨站', '公交5路'),
      segment('metro', 'metro', '小寨站', '大雁塔站', '地铁2号线'),
    ];
    expect(confirmedMetroTransferCount(transportLeg({ segments: mixed, transfer_count: 1 }))).toBe(0);
    expect(confirmedMetroTransferCount(transportLeg({ selected_mode: 'bus', transfer_count: 1 }))).toBe(0);
  });

  it('does not count an operator change on the same metro line', () => {
    const sameLine = [
      { ...segment('metro-1a', 'metro', '钟楼站', '北大街站', '地铁1号线'), operator_name: '运营方甲' },
      { ...segment('metro-1b', 'metro', '北大街站', '小寨站', '地铁1号线'), operator_name: '运营方乙' },
    ];
    expect(confirmedMetroTransferCount(transportLeg({ segments: sameLine, transfer_count: 1 }))).toBe(0);
    expect(legSummary(transportLeg({ segments: sameLine, transfer_count: 1 })).transfer).toBeNull();
  });

  it('labels mixed transit with every ride mode and qualifies each station', () => {
    const mixed = [
      segment('metro', 'metro', '钟楼站', '小寨站', '地铁2号线'),
      segment('bus', 'bus', '小寨站', '大雁塔站', '公交5路'),
    ];
    const leg = transportLeg({
      segments: mixed,
      boarding_stop: endpoint('钟楼站'),
      alighting_stop: endpoint('大雁塔站'),
    });
    expect(transitRideModes(leg)).toEqual(['metro', 'bus']);
    expect(transitDisplayMode(leg)).toBe('metro');
    expect(transitModeLabel(leg)).toBe('地铁 / 公交');
    expect(transitStationModes(leg)).toEqual({ from: 'metro', to: 'bus' });
    expect(transitStations(leg)).toEqual({ from: '钟楼站', to: '大雁塔站' });
  });

  it.each([null, 'M1'])('does not count different trip numbers as a line change with line %s', (lineName) => {
    const trips = [
      { ...segment('trip-471', 'metro', '钟楼站', '北大街站', lineName), service_number: '471' },
      { ...segment('trip-472', 'metro', '北大街站', '小寨站', lineName), service_number: '472' },
    ];
    const leg = transportLeg({ segments: trips, transfer_count: 1 });
    expect(confirmedMetroTransferCount(leg)).toBe(0);
    expect(legSummary(leg).transfer).toBeNull();
  });

  it('keeps the last ride mode when a mixed route returns to metro', () => {
    const mixed = [
      ...walkMetroWalk.slice(0, 2),
      segment('bus', 'bus', '小寨站', '大雁塔站', '公交5路'),
      segment('metro-return', 'metro', '大雁塔站', '钟楼站', '地铁4号线'),
      segment('walk-out', 'walk', '钟楼站', '饭店'),
    ];
    const leg = transportLeg({ segments: mixed });
    expect(transitRideModes(leg)).toEqual(['metro', 'bus']);
    expect(transitModeLabel(leg)).toBe('地铁 / 公交');
    expect(transitStationModes(leg)).toEqual({ from: 'metro', to: 'metro' });
  });

  it('uses provider boarding and alighting stops instead of the POI endpoints', () => {
    expect(transitStations(transportLeg({ segments: walkMetroWalk }))).toEqual({ from: null, to: null });
    expect(transitStations(transportLeg({
      boarding_stop: endpoint('钟楼站'),
      alighting_stop: endpoint('小寨站'),
      segments: walkMetroWalk,
    }))).toEqual({ from: '钟楼站', to: '小寨站' });
  });

  it('keeps airport codes but drops railway station codes', () => {
    expect(showsEndpointCode('flight')).toBe(true);
    expect(showsEndpointCode('high_speed_rail')).toBe(false);
    expect(showsEndpointCode('train')).toBe(false);
  });

  it('hides route actions for high-speed rail and flights while retaining other modes', () => {
    expect(transportRouteActionVisible(transportLeg({ selected_mode: 'high_speed_rail' }))).toBe(false);
    expect(transportRouteActionVisible(transportLeg({ selected_mode: 'flight' }))).toBe(false);
    for (const selected_mode of ['train', 'coach', 'ferry', 'metro', 'drive'] as const) {
      expect(transportRouteActionVisible(transportLeg({ selected_mode }))).toBe(true);
    }
  });
});
