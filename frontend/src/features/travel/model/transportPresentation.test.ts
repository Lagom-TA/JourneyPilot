import { describe, expect, it } from 'vitest';
import { type TransportMode } from '../types/entities';
import { type PublicTransportLeg } from '../types/itinerary';
import {
  TRANSPORT_MODE_COLORS,
  confirmedMetroTransferCount,
  legSummary,
  showsEndpointCode,
  transitDisplayMode,
  transitLineChain,
  transitModeLabel,
  transitRideModes,
  transitRides,
  transitStationModes,
  transitStations,
  transportMapCardLabel,
  transportMapEntryVisible,
  transportModeColor,
  transportModeStyle,
  transportSegmentDisplayMode,
} from './transportPresentation';

function endpoint(name: string, stationCode: string | null = null) {
  return { name, place_id: `place:${name}`, station_code: stationCode, latitude: null, longitude: null };
}

function segment(
  id: string,
  mode: TransportMode,
  from: string,
  to: string,
  lineName: string | null = null,
  options: { serviceNumber?: string | null; operatorName?: string | null; duration?: number | null; distance?: number | null } = {},
) {
  return {
    segment_id: id,
    mode,
    from_endpoint: endpoint(from),
    to_endpoint: endpoint(to),
    departure_at: null,
    arrival_at: null,
    duration_minutes: options.duration ?? null,
    distance_meters: options.distance ?? null,
    operator_name: options.operatorName ?? null,
    service_number: options.serviceNumber ?? null,
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
    expect(summary).toEqual({ duration: '7 小时 49 分钟', cost: '¥1,108' });
  });

  it('does not invent a zero fare when the price is missing', () => {
    const summary = legSummary(transportLeg({ total_cost_cny: null }));
    expect(summary.duration).toBe('42 分钟');
    expect(summary.cost).toBeNull();
  });

  it('keeps transfer wording out of the compact readout', () => {
    const twoLines = [
      segment('metro-2', 'metro', '北大街站', '行政中心站', '地铁2号线'),
      segment('metro-4', 'metro', '行政中心站', '大雁塔站', '地铁4号线'),
    ];
    expect(legSummary(transportLeg({ segments: twoLines, transfer_count: 1 }))).toEqual({
      duration: '42 分钟',
      cost: '¥5',
    });
  });

  it('counts only a real change between metro lines', () => {
    expect(confirmedMetroTransferCount(transportLeg({ segments: walkMetroWalk, transfer_count: 0 }))).toBe(0);
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
    expect(transitLineChain(leg).expandable).toBe(false);
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

  it('hides map entry for high-speed rail and flights while retaining other modes', () => {
    expect(transportMapEntryVisible(transportLeg({ selected_mode: 'high_speed_rail' }))).toBe(false);
    expect(transportMapEntryVisible(transportLeg({ selected_mode: 'flight' }))).toBe(false);
    for (const selected_mode of ['train', 'coach', 'ferry', 'metro', 'drive', 'walk'] as const) {
      expect(transportMapEntryVisible(transportLeg({ selected_mode }))).toBe(true);
    }
  });
});

describe('public transit ride chain', () => {
  it('treats walks and bikes as access, never as route steps', () => {
    const leg = transportLeg({ segments: walkMetroWalk });
    const rides = transitRides(leg);
    expect(rides).toHaveLength(1);
    expect(rides[0].segment.mode).toBe('metro');
    expect(rides[0].label).toBe('地铁2号线');
  });

  it('shows a direct ride without a chain or disclosure', () => {
    const leg = transportLeg({
      segments: walkMetroWalk,
      boarding_stop: endpoint('钟楼站'),
      alighting_stop: endpoint('小寨站'),
    });
    const chain = transitLineChain(leg);
    expect(chain.steps).toHaveLength(1);
    expect(chain.steps[0].label).toBe('地铁2号线');
    expect(chain.steps[0].direction).toBe('小寨站');
    expect(chain.expandable).toBe(false);
    expect(chain.transferCount).toBe(0);
  });

  it('merges a same-line split without inventing a transfer', () => {
    const split = [
      segment('metro-2a', 'metro', '钟楼站', '北大街站', '地铁2号线'),
      segment('metro-2b', 'metro', '北大街站', '小寨站', '地铁2号线'),
    ];
    const leg = transportLeg({
      segments: split,
      boarding_stop: endpoint('钟楼站'),
      alighting_stop: endpoint('小寨站'),
    });
    const chain = transitLineChain(leg);
    expect(chain.rides).toHaveLength(2);
    expect(chain.steps).toHaveLength(1);
    expect(chain.steps[0].label).toBe('地铁2号线');
    expect(chain.steps[0].direction).toBe('小寨站');
    expect(chain.expandable).toBe(false);
  });

  it('builds a real line chain and matches the confirmed metro transfer count', () => {
    const twoLines = [
      segment('metro-2', 'metro', '北大街站', '小寨站', '地铁2号线'),
      segment('metro-4', 'metro', '小寨站', '大雁塔站', '地铁4号线'),
    ];
    const leg = transportLeg({
      segments: twoLines,
      boarding_stop: endpoint('北大街站'),
      alighting_stop: endpoint('大雁塔站'),
      transfer_count: 1,
    });
    const chain = transitLineChain(leg);
    expect(chain.steps.map((step) => step.label)).toEqual(['地铁2号线', '地铁4号线']);
    expect(chain.steps.map((step) => step.direction)).toEqual(['小寨站', '大雁塔站']);
    expect(chain.expandable).toBe(true);
    expect(chain.transferCount).toBe(confirmedMetroTransferCount(leg));
  });

  it('uses different modes as a chain and never reports them as metro transfers', () => {
    const mixed = [
      segment('metro-2', 'metro', '北大街站', '小寨站', '地铁2号线'),
      segment('bus-5', 'bus', '小寨站', '大雁塔站', '公交5路'),
      segment('metro-4', 'metro', '大雁塔站', '钟楼站', '地铁4号线'),
    ];
    const leg = transportLeg({ segments: mixed, transfer_count: 2 });
    const chain = transitLineChain(leg);
    expect(chain.steps.map((step) => step.label)).toEqual(['地铁2号线', '公交5路', '地铁4号线']);
    expect(chain.transferCount).toBe(2);
    expect(confirmedMetroTransferCount(leg)).toBe(0);
  });

  it('falls back to the mode label and never fakes a direction without a proven stop', () => {
    const leg = transportLeg({
      segments: [segment('metro-4b', 'metro', '陕西历史博物馆', '子午路张记肉夹馍（小寨店）')],
    });
    const chain = transitLineChain(leg);
    expect(chain.steps[0].label).toBe('地铁');
    expect(chain.steps[0].direction).toBeNull();
    expect(chain.expandable).toBe(false);
    expect(transitRides(leg)[0].direction).toBeNull();
  });

  it('does not infer a transfer when a line identity is missing', () => {
    const partial = [
      segment('metro-2', 'metro', '北大街站', '小寨站', '地铁2号线'),
      segment('metro-unknown', 'metro', '小寨站', '大雁塔站'),
    ];
    const chain = transitLineChain(transportLeg({ segments: partial }));
    expect(chain.steps).toHaveLength(1);
    expect(chain.steps[0].label).toBe('地铁');
    expect(chain.expandable).toBe(false);
  });

  it('keeps a long line name compact on the first screen and complete in the ride row', () => {
    const tram = segment('tram-103', 'tram', '东安门大街站', '神武门站', '103路(北京站西--动物园枢纽站)');
    const leg = transportLeg({
      selected_mode: 'tram',
      segments: [
        segment('walk-in', 'walk', '东安门大街', '东安门大街站'),
        tram,
        segment('walk-out', 'walk', '神武门站', '神武门'),
      ],
      boarding_stop: endpoint('东安门大街站'),
      alighting_stop: endpoint('神武门站'),
    });
    const chain = transitLineChain(leg);
    expect(chain.steps[0].label).toBe('103路');
    expect(chain.rides[0].rowLabel).toBe('103路(北京站西--动物园枢纽站)');
    expect(chain.steps[0].direction).toBe('神武门站');
  });

  it('prefers the service number for the line label', () => {
    const tram = segment('tram-103', 'tram', '东安门大街站', '神武门站', '103路(北京站西--动物园枢纽站)', {
      serviceNumber: '103',
    });
    const leg = transportLeg({ selected_mode: 'tram', segments: [tram] });
    expect(transitLineChain(leg).steps[0].label).toBe('103');
  });

  it('takes each ride direction from the next boarding stop and the final alighting stop', () => {
    const twoLines = [
      segment('metro-2', 'metro', '北大街站', '小寨站', '地铁2号线'),
      segment('metro-4', 'metro', '小寨站', '大雁塔站', '地铁4号线'),
    ];
    const leg = transportLeg({
      segments: twoLines,
      alighting_stop: endpoint('大雁塔站'),
    });
    expect(transitRides(leg).map((ride) => ride.direction)).toEqual(['小寨站', '大雁塔站']);
  });

  it('describes line, stations and map action in the card accessible name', () => {
    const leg = transportLeg({
      segments: walkMetroWalk,
      boarding_stop: endpoint('钟楼站'),
      alighting_stop: endpoint('小寨站'),
    });
    const label = transportMapCardLabel(leg);
    expect(label).toContain('地铁2号线');
    expect(label).toContain('钟楼站到小寨站');
    expect(label).toContain('42 分钟');
    expect(label).toContain('¥5');
    expect(label).toContain('在地图中查看');
  });
});
