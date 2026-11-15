import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { PlaceIdentity } from '../types/planner';
import { COMMON_PLACES } from './commonPlaces';
import { INSPIRATION_PLACES } from './inspirationPlaces';
import {
  createPlaceSearchRunner,
  findLocalPlaceCandidates,
  PLACE_SEARCH_TIMEOUT_MS,
  samePlace,
  type PlaceSearchCandidate,
} from './placeSearch';

function candidate(name: string, overrides: Partial<PlaceIdentity> = {}): PlaceSearchCandidate {
  return {
    place: {
      place_id: `osm:node:${name}`,
      provider: 'osm',
      kind: 'city',
      name,
      display_name: name,
      country_code: 'CN',
      latitude: 10,
      longitude: 20,
      admin_path: [],
      ...overrides,
    },
    confidence: 0.8,
  };
}

function sink() {
  return { setLoading: vi.fn(), setError: vi.fn(), setCandidates: vi.fn() };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

let testTime = Date.UTC(2026, 0, 1);
beforeEach(() => {
  vi.useFakeTimers();
  testTime += 60 * 60_000;
  vi.setSystemTime(testTime);
});
afterEach(() => { vi.useRealTimers(); });

describe('place search', () => {
  it('matches local names and display names, deduplicates cities and isolates roles', async () => {
    const beijing = INSPIRATION_PLACES.beijing;
    const osmCity = candidate('北京', {
      ...beijing,
      place_id: 'osm:relation:test-beijing',
      provider: 'osm',
      country_code: 'cn',
      latitude: beijing.latitude + 0.005,
    });
    const airport = candidate('北京机场', {
      kind: 'airport',
      display_name: 'Beijing   International Airport',
    });
    const island = candidate('北京岛', { kind: 'island' });
    const fetcher = vi.fn(async () => ({ candidates: [osmCity, airport, island] }));
    const runner = createPlaceSearchRunner('origin', fetcher);

    expect(findLocalPlaceCandidates(' 北 ', 'origin').some(({ place }) => samePlace(place, beijing))).toBe(true);
    expect(findLocalPlaceCandidates(COMMON_PLACES[0].name, 'destination')
      .some(({ place }) => samePlace(place, COMMON_PLACES[0]))).toBe(true);
    expect(fetcher).not.toHaveBeenCalled();
    await runner.run('北京', sink());

    const origin = findLocalPlaceCandidates('北京', 'origin');
    expect(origin.filter(({ place }) => samePlace(place, beijing)).map(({ place }) => place.place_id))
      .toEqual([COMMON_PLACES[0].place_id]);
    expect(origin.some(({ place }) => place.kind === 'airport')).toBe(true);
    expect(origin.some(({ place }) => place.kind === 'island')).toBe(false);
    expect(findLocalPlaceCandidates('  BEIJING   INTERNATIONAL  ', 'origin').map(({ place }) => place))
      .toContain(airport.place);
    expect(findLocalPlaceCandidates('北京', 'destination').some(({ place }) => place.place_id === airport.place.place_id))
      .toBe(false);
    expect(samePlace(beijing, { ...beijing, place_id: 'other', name: '北京市' })).toBe(true);
    expect(samePlace(beijing, { ...beijing, place_id: 'other', latitude: beijing.latitude + 1 })).toBe(false);
    expect(samePlace(beijing, { ...beijing, place_id: 'other', country_code: 'US' })).toBe(false);
    expect(samePlace(beijing, { ...beijing, kind: 'airport' })).toBe(false);
  });

  it('caches normalized queries by role, expires them and evicts old local results', async () => {
    const fetcher = vi.fn(async (query: string) => ({ candidates: [candidate(query)] }));
    const origin = createPlaceSearchRunner('origin', fetcher);
    const destination = createPlaceSearchRunner('destination', fetcher);
    const result = sink();

    await origin.run('  Cache   Town  ', result);
    expect(findLocalPlaceCandidates('cache town', 'origin')).toHaveLength(1);
    expect(findLocalPlaceCandidates('cache town', 'destination')).toHaveLength(0);
    await origin.run('cache town', result);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await destination.run('cache town', result);
    expect(fetcher).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(5 * 60_000);
    expect(findLocalPlaceCandidates('cache town', 'origin')).toHaveLength(0);
    expect(findLocalPlaceCandidates('cache town', 'destination')).toHaveLength(0);
    await origin.run('cache town', result);
    expect(fetcher).toHaveBeenCalledTimes(3);

    for (let i = 0; i <= 40; i += 1) {
      await origin.run(`Evict city ${String(i).padStart(2, '0')}`, result);
    }
    expect(findLocalPlaceCandidates('Evict city 00', 'origin')).toHaveLength(0);
    expect(findLocalPlaceCandidates('Evict city 01', 'origin')).toHaveLength(1);
  });

  it('reuses in-flight searches and ignores responses after replacement or cancellation', async () => {
    const requests: Array<{ signal: AbortSignal; result: ReturnType<typeof deferred<{ candidates: PlaceSearchCandidate[] }>> }> = [];
    const fetcher = vi.fn((_query: string, _role: 'origin' | 'destination', { signal }: { signal: AbortSignal }) => {
      const result = deferred<{ candidates: PlaceSearchCandidate[] }>();
      requests.push({ signal, result });
      return result.promise;
    });
    const runner = createPlaceSearchRunner('origin', fetcher);
    const firstSink = sink();
    const latestSink = sink();
    const first = runner.run('Inflight City', firstSink);
    const repeated = runner.run('  inflight   city ', latestSink);
    expect(repeated).toBe(first);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(requests[0].signal.aborted).toBe(false);
    requests[0].result.resolve({ candidates: [candidate('Inflight City')] });
    await repeated;
    expect(firstSink.setCandidates).not.toHaveBeenCalled();
    expect(latestSink.setCandidates).toHaveBeenCalledOnce();

    const superseded = runner.run('Superseded City', firstSink);
    const cancelled = runner.run('Cancelled City', latestSink);
    expect(requests[1].signal.aborted).toBe(true);
    runner.cancel();
    expect(requests[2].signal.aborted).toBe(true);
    requests[1].result.resolve({ candidates: [candidate('Superseded City')] });
    requests[2].result.resolve({ candidates: [candidate('Cancelled City')] });
    await Promise.all([superseded, cancelled]);
    expect(firstSink.setCandidates).not.toHaveBeenCalled();
    expect(latestSink.setCandidates).toHaveBeenCalledOnce();
    expect(findLocalPlaceCandidates('Superseded City', 'origin')).toHaveLength(0);
    expect(findLocalPlaceCandidates('Cancelled City', 'origin')).toHaveLength(0);
  });

  it('does not cache failures or empty results', async () => {
    const fetcher = vi.fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ candidates: [] })
      .mockResolvedValue({ candidates: [candidate('Retry City')] });
    const runner = createPlaceSearchRunner('destination', fetcher);
    const result = sink();
    await runner.run('Retry City', result);
    expect(result.setError).toHaveBeenLastCalledWith('无法连接服务，读不到地点候选，请检查网络后重试。');
    await runner.run('Retry City', result);
    expect(result.setError).toHaveBeenLastCalledWith('请选择城市、行政区域、岛屿或景区型区域');
    await runner.run('Retry City', result);
    await runner.run('Retry City', result);
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(findLocalPlaceCandidates('Retry City', 'destination')).toHaveLength(1);
  });

  it('times out even if the fetcher ignores abort, without caching its late response', async () => {
    const response = deferred<{ candidates: PlaceSearchCandidate[] }>();
    const fetcher = vi.fn(() => response.promise);
    const runner = createPlaceSearchRunner('origin', fetcher);
    const result = sink();
    const pending = runner.run('Timeout City', result);
    await vi.advanceTimersByTimeAsync(PLACE_SEARCH_TIMEOUT_MS);
    await pending;
    expect(result.setError).toHaveBeenLastCalledWith('地点搜索超时，请重试');
    expect(result.setLoading).toHaveBeenLastCalledWith(false);
    response.resolve({ candidates: [candidate('Timeout City')] });
    await Promise.resolve();
    expect(result.setCandidates).not.toHaveBeenCalled();
    expect(findLocalPlaceCandidates('Timeout City', 'origin')).toHaveLength(0);
  });
});
