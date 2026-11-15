import { describeRequestFailure } from '../../../lib/requestFailureMessage';
import { searchPlaces } from '../api/places';
import type { PlaceIdentity, PlaceKind } from '../types/planner';
import { COMMON_PLACES } from './commonPlaces';
import { INSPIRATION_PLACES } from './inspirationPlaces';

export const PLACE_SEARCH_TIMEOUT_MS = 30_000;
const CACHE_TTL_MS = 5 * 60_000;
const CACHE_CAPACITY = 40;
const SAME_CITY_DISTANCE_KM = 10;

export type PlaceSearchRole = 'origin' | 'destination';
export interface PlaceSearchCandidate {
  place: PlaceIdentity;
  confidence: number;
}
export interface PlaceSearchSink {
  setLoading(value: boolean): void;
  setError(message: string): void;
  setCandidates(candidates: PlaceSearchCandidate[]): void;
}
type PlaceSearchFetcher = (query: string, role: PlaceSearchRole, options: {
  signal: AbortSignal;
}) => Promise<{
  candidates: PlaceSearchCandidate[];
}>;
export interface PlaceSearchRunner {
  run(query: string, sink: PlaceSearchSink): Promise<void>;
  cancel(): void;
}

const EMPTY_RESULT_MESSAGE: Record<PlaceSearchRole, string> = {
  origin: '没有找到可用的城市或机场',
  destination: '请选择城市、行政区域、岛屿或景区型区域',
};
const ALLOWED_KINDS: Record<PlaceSearchRole, readonly PlaceKind[]> = {
  origin: ['city', 'airport', 'train_station'],
  destination: ['city', 'administrative_area', 'island', 'scenic_area'],
};

type CacheEntry = { candidates: PlaceSearchCandidate[]; expiresAt: number };
const cache: Record<PlaceSearchRole, Map<string, CacheEntry>> = {
  origin: new Map(),
  destination: new Map(),
};

function cleanWhitespace(value: string): string {
  return value.trim().replace(/\s+/g, ' ');
}

function normalize(value: string): string {
  return cleanWhitespace(value).toLowerCase();
}

function cityName(name: string, countryCode: string): string {
  const normalized = normalize(name);
  return normalize(countryCode) === 'cn' ? normalized.replace(/市$/, '') : normalized;
}

function pruneExpired(entries: Map<string, CacheEntry>): void {
  const now = Date.now();
  for (const [key, entry] of entries) {
    if (entry.expiresAt <= now) entries.delete(key);
  }
}

function cachedCandidates(role: PlaceSearchRole, key: string): PlaceSearchCandidate[] | undefined {
  const entries = cache[role];
  pruneExpired(entries);
  const entry = entries.get(key);
  if (!entry) return undefined;
  entries.delete(key);
  entries.set(key, entry);
  return entry.candidates;
}

function cacheCandidates(role: PlaceSearchRole, key: string, candidates: PlaceSearchCandidate[]): void {
  const entries = cache[role];
  pruneExpired(entries);
  entries.delete(key);
  entries.set(key, { candidates: [...candidates], expiresAt: Date.now() + CACHE_TTL_MS });
  if (entries.size > CACHE_CAPACITY) entries.delete(entries.keys().next().value!);
}

export function samePlace(a: PlaceIdentity, b: PlaceIdentity): boolean {
  if (a.kind !== b.kind) return false;
  if (a.place_id === b.place_id) return true;
  if (
    a.kind !== 'city'
    || cityName(a.name, a.country_code) !== cityName(b.name, b.country_code)
    || normalize(a.country_code) !== normalize(b.country_code)
  ) return false;

  const radians = Math.PI / 180;
  const latitudeDifference = (b.latitude - a.latitude) * radians;
  const longitudeDifference = (b.longitude - a.longitude) * radians;
  const haversine = Math.sin(latitudeDifference / 2) ** 2
    + Math.cos(a.latitude * radians) * Math.cos(b.latitude * radians)
    * Math.sin(longitudeDifference / 2) ** 2;
  const distanceKm = 2 * 6371.0088 * Math.asin(Math.min(1, Math.sqrt(haversine)));
  return distanceKm <= SAME_CITY_DISTANCE_KM;
}

function matchRank(place: PlaceIdentity, query: string): number {
  const name = normalize(place.name);
  const displayName = normalize(place.display_name);
  if (name === query) return 0;
  if (name.startsWith(query)) return 1;
  if (name.includes(query)) return 2;
  if (displayName === query) return 3;
  if (displayName.startsWith(query)) return 4;
  if (displayName.includes(query)) return 5;
  return -1;
}

function deduplicate(candidates: PlaceSearchCandidate[]): PlaceSearchCandidate[] {
  const unique: PlaceSearchCandidate[] = [];
  for (const candidate of candidates) {
    if (!unique.some((existing) => samePlace(existing.place, candidate.place))) unique.push(candidate);
  }
  return unique;
}

export function findLocalPlaceCandidates(query: string, role: PlaceSearchRole): PlaceSearchCandidate[] {
  const key = normalize(query);
  if (!key) return [];
  const entries = cache[role];
  pruneExpired(entries);
  const presets = [...COMMON_PLACES, ...Object.values(INSPIRATION_PLACES)]
    .map((place) => ({ place, confidence: 1 }));
  const remote = [...entries.values()].flatMap((entry) => entry.candidates);
  const ranked = [...presets, ...remote]
    .filter(({ place }) => ALLOWED_KINDS[role].includes(place.kind))
    .map((candidate, index) => ({ candidate, index, rank: matchRank(candidate.place, key) }))
    .filter(({ rank }) => rank >= 0)
    .sort((a, b) => a.rank - b.rank || a.index - b.index);
  return deduplicate(ranked.map(({ candidate }) => candidate));
}

function isAbort(reason: unknown): boolean {
  return (reason as { name?: string } | null)?.name === 'AbortError';
}

export function createPlaceSearchRunner(role: PlaceSearchRole, fetcher: PlaceSearchFetcher = searchPlaces): PlaceSearchRunner {
  type ActiveSearch = {
    key: string;
    controller: AbortController;
    sink: PlaceSearchSink;
    clock: ReturnType<typeof setTimeout>;
    promise: Promise<void>;
  };
  let latest = 0;
  let active: ActiveSearch | null = null;

  function cancel(): void {
    latest += 1;
    if (!active) return;
    const previous = active;
    active = null;
    clearTimeout(previous.clock);
    previous.controller.abort();
  }

  return {
    cancel,
    run(query, sink) {
      const cleanedQuery = cleanWhitespace(query);
      const key = normalize(cleanedQuery);
      if (active?.key === key) {
        active.sink = sink;
        sink.setLoading(true);
        sink.setError('');
        return active.promise;
      }

      cancel();
      const cached = cachedCandidates(role, key);
      if (cached) {
        sink.setLoading(false);
        sink.setError('');
        sink.setCandidates([...cached]);
        return Promise.resolve();
      }

      const ticket = latest;
      const controller = new AbortController();
      let timedOut = false;
      let rejectAbort: () => void = () => {};
      const aborted = new Promise<never>((_, reject) => {
        rejectAbort = () => reject(Object.assign(new Error('Aborted'), { name: 'AbortError' }));
        controller.signal.addEventListener('abort', rejectAbort, { once: true });
      });
      const entry: ActiveSearch = {
        key,
        controller,
        sink,
        clock: setTimeout(() => {
          timedOut = true;
          controller.abort();
        }, PLACE_SEARCH_TIMEOUT_MS),
        promise: Promise.resolve(),
      };
      active = entry;
      const isCurrent = () => ticket === latest && active === entry;
      sink.setLoading(true);
      sink.setError('');

      entry.promise = (async () => {
        try {
          const result = await Promise.race([fetcher(cleanedQuery, role, { signal: controller.signal }), aborted]);
          if (!isCurrent() || controller.signal.aborted) return;
          const candidates = deduplicate(result.candidates.filter(({ place }) => ALLOWED_KINDS[role].includes(place.kind)));
          if (candidates.length) cacheCandidates(role, key, candidates);
          entry.sink.setCandidates([...candidates]);
          if (!candidates.length) entry.sink.setError(EMPTY_RESULT_MESSAGE[role]);
        } catch (reason) {
          if (!isCurrent()) return;
          if (timedOut) entry.sink.setError('地点搜索超时，请重试');
          else if (!isAbort(reason)) entry.sink.setError(describeRequestFailure(reason, '读取', '地点候选').message);
        } finally {
          controller.signal.removeEventListener('abort', rejectAbort);
          if (isCurrent()) {
            clearTimeout(entry.clock);
            active = null;
            entry.sink.setLoading(false);
          }
        }
      })();
      return entry.promise;
    },
  };
}
