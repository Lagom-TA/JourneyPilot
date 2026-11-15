import React from 'react';
import {
  createPlaceSearchRunner,
  findLocalPlaceCandidates,
  samePlace,
  type PlaceSearchCandidate,
  type PlaceSearchRole,
} from '../../model/placeSearch';

export function usePlaceSearch(role: PlaceSearchRole, query: string, active: boolean) {
  const runner = React.useMemo(() => createPlaceSearchRunner(role), [role]);
  const [remote, setRemote] = React.useState<{ query: string; candidates: PlaceSearchCandidate[] } | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState('');
  const currentQuery = React.useRef(query);
  currentQuery.current = query;
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  const cancel = React.useCallback(() => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
    runner.cancel();
    setRemote(null);
    setLoading(false);
    setError('');
  }, [runner]);

  const search = React.useCallback(() => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
    const text = currentQuery.current.trim();
    if (text.length < 2) return;
    void runner.run(text, {
      setLoading,
      setError,
      setCandidates: (candidates) => setRemote({ query: text, candidates }),
    });
  }, [runner]);

  React.useEffect(() => {
    cancel();
    if (active && query.trim().length >= 2) {
      timer.current = setTimeout(search, 280);
    }
    return () => {
      if (timer.current !== null) clearTimeout(timer.current);
      timer.current = null;
      runner.cancel();
    };
  }, [active, query, cancel, runner, search]);

  const candidates = findLocalPlaceCandidates(query, role);
  for (const candidate of remote?.query === query.trim() ? remote.candidates : []) {
    const index = candidates.findIndex(({ place }) => samePlace(place, candidate.place));
    if (index < 0) candidates.push(candidate);
  }

  return { candidates, loading, error, search, cancel };
}
