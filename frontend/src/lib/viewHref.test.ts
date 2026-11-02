import { describe, expect, it } from 'vitest';
import { resolveViewHref } from './viewHref';

describe('resolveViewHref', () => {
  it('keeps the root deployment unchanged', () => {
    expect(resolveViewHref('chat', '/')).toBe('/?view=chat');
    expect(resolveViewHref('trips', undefined)).toBe('/?view=trips');
  });

  it('prefixes sub-path deployments with their base', () => {
    expect(resolveViewHref('presets', '/journeypilot/')).toBe('/journeypilot/?view=presets');
    expect(resolveViewHref('knowledge-base', '/journeypilot')).toBe('/journeypilot/?view=knowledge-base');
  });

  it('encodes the view parameter', () => {
    expect(resolveViewHref('a b', '/')).toBe('/?view=a%20b');
  });
});
