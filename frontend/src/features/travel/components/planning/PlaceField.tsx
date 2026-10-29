import { MapPin } from 'lucide-react';
import { createPlaceSearchRunner, type PlaceSearchCandidate } from '../../model/placeSearch';
import { FIELD_LABEL, FIELD_VALUE, RULED_FIELD } from '../../../../components/ui/Input';
import { cn } from '../../../../lib/utils';
import { type PlaceIdentity } from '../../types/planner';
import React from 'react';

export const PlaceField: React.FC<{
  role: 'origin' | 'destination';
  value: PlaceIdentity | null;
  onChange: (value: PlaceIdentity | null) => void;
  label: string;
  frequent?: boolean;
  initialQuery?: string;
  onQueryChange?: (query: string) => void;
  className?: string;
}> = ({ role, value, onChange, label, frequent, initialQuery = '', onQueryChange, className }) => {
  const [query, setQuery] = React.useState(value?.name || initialQuery);
  const [candidates, setCandidates] = React.useState<PlaceSearchCandidate[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState('');
  const runner = React.useMemo(() => createPlaceSearchRunner(role), [role]);
  React.useEffect(() => () => runner.cancel(), [runner]);

  const search = React.useCallback(async (raw: string) => {
    const q = raw.trim();
    if (q.length < 2) return;
    await runner.run(q, { setLoading, setError, setCandidates });
  }, [runner]);

  React.useEffect(() => {
    if (value) setQuery(value.name);
  }, [value]);

  React.useEffect(() => {
    if (!value && initialQuery) setQuery(initialQuery);
  }, [initialQuery]);

  React.useEffect(() => {
    const q = query.trim();
    if (q.length < 2 || q === value?.name) {
      runner.cancel();
      setCandidates([]);
      setError('');
      setLoading(false);
      return;
    }
    const timer = window.setTimeout(() => void search(q), 280);
    return () => window.clearTimeout(timer);
  }, [query, value?.name, search, runner]);

  return (
    <div className={cn('relative min-w-0 flex-1', className)}>
      <label className={FIELD_LABEL}>{label}</label>
      <div className={RULED_FIELD}>
        <MapPin size={15} className="shrink-0 text-accent" />
        <input
          value={query}
          onChange={(event) => { setQuery(event.target.value); onQueryChange?.(event.target.value); if (value) onChange(null); }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              void search(query);
            }
          }}
          className={cn('min-w-0 flex-1 bg-transparent py-2', FIELD_VALUE)}
          placeholder={role === 'origin' ? '城市、机场或火车站' : '城市或区域'}
          aria-label={label}
          autoComplete="off"
        />
        {frequent && value && <span className="rounded-label bg-chart/8 px-1.5 py-0.5 text-[11px] text-chart">常用</span>}
        {loading && <span className="text-[11px] text-ink-muted">搜索中…</span>}
      </div>

      {(candidates.length > 0 || error) && (
        <div className="absolute z-30 mt-1 max-h-64 w-full overflow-y-auto rounded-card border border-stroke bg-panel p-1 shadow-lg">
          {candidates.map(({ place }) => (
            <button
              key={place.place_id}
              type="button"
              onClick={() => {
                onChange(place);
                setCandidates([]);
                setError('');
              }}
              className="flex min-h-11 w-full items-start gap-2 rounded-label px-3 py-2 text-left transition-colors hover:bg-accent-soft"
            >
              <MapPin size={14} className="mt-0.5 shrink-0 text-accent" />
              <span className="min-w-0">
                <strong className="block truncate text-sm font-medium text-ink">{place.name}</strong>
                <span className="block truncate text-xs text-ink-secondary">{place.display_name}</span>
              </span>
            </button>
          ))}
          {error && <p role="status" className="px-3 py-2 text-xs text-error">{error}</p>}
        </div>
      )}
    </div>
  );
};
