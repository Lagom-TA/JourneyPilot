import { describe, expect, it } from 'vitest';
import { type TransportMode } from '../types/entities';
import {
  TRANSPORT_MODE_COLORS,
  transportModeColor,
  transportModeStyle,
  transportSegmentDisplayMode,
} from './transportPresentation';

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
