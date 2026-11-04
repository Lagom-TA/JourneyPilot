import { useMemo, useSyncExternalStore } from 'react';
import { VIEWPORT_QUERIES } from '../lib/breakpoints';

/* 入口与 Sheet 共用断点，避免移动端触点与容器形态不一致。 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useMemo(() => (callback: () => void) => {
    const mql = window.matchMedia(query);
    mql.addEventListener('change', callback);
    return () => mql.removeEventListener('change', callback);
  }, [query]);
  const getSnapshot = useMemo(() => () => window.matchMedia(query).matches, [query]);
  return useSyncExternalStore(subscribe, getSnapshot);
}

export function useIsMobileViewport(): boolean {
  return useMediaQuery(VIEWPORT_QUERIES.mobile);
}

export function useIsCompactViewport(): boolean {
  return useMediaQuery(VIEWPORT_QUERIES.compact);
}
