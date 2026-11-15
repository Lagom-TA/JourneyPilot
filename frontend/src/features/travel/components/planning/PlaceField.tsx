import { MapPin } from 'lucide-react';
import { FIELD_LABEL, FIELD_VALUE, RULED_FIELD } from '../../../../components/ui/Input';
import { cn } from '../../../../lib/utils';
import { type PlaceIdentity } from '../../types/planner';
import { usePlaceSearch } from './usePlaceSearch';
import React from 'react';

export const PlaceField: React.FC<{
  role: 'origin' | 'destination';
  value: PlaceIdentity | null;
  onChange: (value: PlaceIdentity | null) => void;
  label: string;
  frequent?: boolean;
  initialQuery?: string;
  onQueryChange?: (query: string) => void;
  active?: boolean;
  showAttribution?: boolean;
  className?: string;
}> = ({ role, value, onChange, label, frequent, initialQuery = '', onQueryChange, active = true, showAttribution = true, className }) => {
  const rootRef = React.useRef<HTMLDivElement>(null);
  const composingRef = React.useRef(false);
  const [query, setQuery] = React.useState(value?.name || initialQuery);
  const [focused, setFocused] = React.useState(false);
  const [composing, setComposing] = React.useState(false);
  const valueRef = React.useRef(value);
  valueRef.current = value;
  const { candidates, loading, error, search, cancel } = usePlaceSearch(role, query, active && focused && !composing && query.trim() !== value?.name);
  const closeCandidates = React.useCallback(() => {
    cancel();
    setFocused(false);
  }, [cancel]);

  React.useEffect(() => {
    if (!active) closeCandidates();
  }, [active, closeCandidates]);

  React.useEffect(() => {
    if (value) setQuery(value.name);
  }, [value]);

  React.useEffect(() => {
    if (!valueRef.current && initialQuery) setQuery(initialQuery);
  }, [initialQuery]);

  const submitSearch = () => {
    if (composingRef.current) return;
    setFocused(true);
    search();
  };

  const showCandidates = active && focused && !composing && query.trim() !== value?.name && (candidates.length > 0 || Boolean(error));

  return (
    <div
      ref={rootRef}
      className={cn('relative min-w-0 flex-1', className)}
      onBlur={() => {
        window.setTimeout(() => {
          if (!rootRef.current?.contains(document.activeElement)) closeCandidates();
        }, 0);
      }}
    >
      <label className={FIELD_LABEL}>{label}</label>
      <div className={RULED_FIELD}>
        <MapPin size={15} className="shrink-0 text-accent" />
        <input
          value={query}
          onChange={(event) => {
            cancel();
            setFocused(true);
            setQuery(event.target.value);
            onQueryChange?.(event.target.value);
            if (value) onChange(null);
          }}
          onFocus={() => setFocused(true)}
          onCompositionStart={() => {
            composingRef.current = true;
            setComposing(true);
            cancel();
          }}
          onCompositionEnd={() => {
            composingRef.current = false;
            setComposing(false);
          }}
          onKeyDown={(event) => {
            if (event.nativeEvent.isComposing || composingRef.current) return;
            if (event.key === 'Escape') {
              event.preventDefault();
              closeCandidates();
              return;
            }
            if (event.key === 'Enter') {
              event.preventDefault();
              submitSearch();
            }
          }}
          className={cn('min-w-0 flex-1 bg-transparent py-2', FIELD_VALUE)}
          placeholder={role === 'origin' ? '选择城市' : '城市或区域'}
          aria-label={label}
          autoComplete="off"
        />
        {frequent && value && <span className="rounded-label bg-chart/8 px-1.5 py-0.5 text-[11px] text-chart">常用</span>}
        {loading && <span className="shrink-0 text-[11px] text-ink-muted" role="status">搜索中…</span>}
      </div>
      {showAttribution && <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer" className="block text-[10px] text-ink-muted">地点数据 © OpenStreetMap contributors</a>}

      {showCandidates && (
        <div className="absolute z-30 mt-1 max-h-64 w-full overflow-y-auto rounded-card border border-stroke bg-panel p-1 shadow-lg">
          {candidates.map(({ place }) => (
            <button
              key={place.place_id}
              type="button"
              onClick={() => {
                closeCandidates();
                onChange(place);
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
