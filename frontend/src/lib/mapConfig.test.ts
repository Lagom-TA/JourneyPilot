import { describe, expect, it } from 'vitest';
import { resolveMapTileConfig } from './mapConfig';

describe('resolveMapTileConfig', () => {
  it('keeps the current tile provider by default', () => {
    const config = resolveMapTileConfig(undefined, undefined);
    expect(config.url).toContain('webrd0{s}.is.autonavi.com');
    expect(config.attribution).toContain('高德地图');
    expect(config.subdomains).toEqual(['1', '2', '3', '4']);
    expect(config.datum).toBe('gcj02');
  });

  it('accepts an explicit datum and rejects unknown values', () => {
    expect(resolveMapTileConfig(undefined, undefined, ' WGS84 ').datum).toBe('wgs84');
    expect(resolveMapTileConfig(undefined, undefined, 'gcj02').datum).toBe('gcj02');
    expect(() => resolveMapTileConfig(undefined, undefined, 'invalid')).toThrow('VITE_MAP_TILE_DATUM');
  });

  it('uses configured tile url and attribution', () => {
    const config = resolveMapTileConfig('https://tiles.example.org/{z}/{x}/{y}.png', '<a href="https://example.org">Example</a>');
    expect(config.url).toBe('https://tiles.example.org/{z}/{x}/{y}.png');
    expect(config.attribution).toBe('<a href="https://example.org">Example</a>');
    expect(config.subdomains).toBeUndefined();
  });

  it('trims and ignores empty overrides', () => {
    const config = resolveMapTileConfig('  ', ' ');
    expect(config.url).toContain('autonavi.com');
    expect(config.attribution).toContain('高德地图');
  });
});
