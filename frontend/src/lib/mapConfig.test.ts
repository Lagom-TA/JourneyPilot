import { describe, expect, it } from 'vitest';
import { resolveMapTileConfig } from './mapConfig';

describe('resolveMapTileConfig', () => {
  it('keeps the current tile provider by default', () => {
    const config = resolveMapTileConfig(undefined, undefined);
    expect(config.url).toContain('webrd0{s}.is.autonavi.com');
    expect(config.attribution).toContain('高德地图');
    expect(config.subdomains).toEqual(['1', '2', '3', '4']);
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
