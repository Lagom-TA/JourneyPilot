import { useSyncExternalStore } from 'react';

/* 入口与 Sheet 共用断点，避免移动端触点与容器形态不一致。 */
const MOBILE_QUERY = '(max-width: 1023.98px)';

function subscribe(callback: () => void): () => void {
  const mql = window.matchMedia(MOBILE_QUERY);
  mql.addEventListener('change', callback);
  return () => mql.removeEventListener('change', callback);
}

function getSnapshot(): boolean {
  return window.matchMedia(MOBILE_QUERY).matches;
}

export function useIsMobileViewport(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot);
}
