import { describe, expect, it } from 'vitest';
import { ApiError } from '../../lib/http';
import { shouldRetryWeatherRefresh, shouldStartWeatherRefresh, weatherRetryDelayMs } from './weatherRefreshPolicy';

describe('shouldStartWeatherRefresh', () => {
  const base = { enabled: true, bundleId: 'bundle-1', attempted: new Set<string>(), inFlight: new Set<string>() };

  it('starts an un-attempted bundle once', () => {
    expect(shouldStartWeatherRefresh(base)).toBe(true);
  });

  it('does not start when disabled, missing, attempted or in flight', () => {
    expect(shouldStartWeatherRefresh({ ...base, enabled: false })).toBe(false);
    expect(shouldStartWeatherRefresh({ ...base, bundleId: null })).toBe(false);
    expect(shouldStartWeatherRefresh({ ...base, attempted: new Set(['bundle-1']) })).toBe(false);
    expect(shouldStartWeatherRefresh({ ...base, inFlight: new Set(['bundle-1']) })).toBe(false);
  });
});

describe('shouldRetryWeatherRefresh', () => {
  it('retries transient and network failures but not conflicts or client errors', () => {
    expect(shouldRetryWeatherRefresh(new Error('network'))).toBe(true);
    expect(shouldRetryWeatherRefresh(new ApiError('busy', 429, null))).toBe(true);
    expect(shouldRetryWeatherRefresh(new ApiError('down', 503, null))).toBe(true);
    expect(shouldRetryWeatherRefresh(new ApiError('conflict', 409, null))).toBe(false);
    expect(shouldRetryWeatherRefresh(new ApiError('bad request', 400, null))).toBe(false);
  });
});

describe('weatherRetryDelayMs', () => {
  it('backs off exponentially', () => {
    expect([1, 2, 3].map(weatherRetryDelayMs)).toEqual([150, 300, 600]);
  });
});
