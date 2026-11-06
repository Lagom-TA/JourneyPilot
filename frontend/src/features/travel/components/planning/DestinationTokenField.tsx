import { Check, MapPin, Plus, X } from 'lucide-react';
import { createPortal } from 'react-dom';
import { createPlaceSearchRunner, type PlaceSearchCandidate } from '../../model/placeSearch';
import type { PlaceIdentity } from '../../types/planner';
import { cn } from '../../../../lib/utils';
import React from 'react';

export const MAX_DESTINATIONS = 5;

type Values = Array<PlaceIdentity | null>;

export type DestinationAddState = 'base' | 'open' | 'closed' | 'limit';

interface DestinationTokenFieldProps {
  values: Values;
  queries: string[];
  onChange: (values: Values, queries: string[]) => void;
  className?: string;
  /** 首页规划卡用它把“新增搜索是否展开”同步到外层布局，其他入口可不传。 */
  onAddStateChange?: (state: DestinationAddState) => void;
}

const DRAFT_SEPARATOR = '\u0001';
// 收起后保留搜索节点到动画结束，避免收起瞬间整行消失导致外层布局先跳动再复位。
const ADD_PANEL_UNMOUNT_DELAY_MS = 260;

function confirmedPlaces(values: Values): PlaceIdentity[] {
  return values.filter((place): place is PlaceIdentity => Boolean(place));
}

function restoredDrafts(values: Values, queries: string[]): string[] {
  const confirmedCount = values.filter(Boolean).length;
  return queries
    .slice(confirmedCount)
    .map((query) => query.trim())
    .filter(Boolean);
}

function queriesFor(places: PlaceIdentity[], drafts: string[], open: boolean): string[] {
  const queries = places.map((place) => place.name);
  if (open) {
    for (const draft of drafts) {
      const trimmed = draft.trim();
      if (trimmed) queries.push(trimmed);
    }
  }
  return queries;
}

const DestinationSearch: React.FC<{
  query: string;
  selectedIds: Set<string>;
  inputRef: (node: HTMLInputElement | null) => void;
  onQueryChange: (query: string) => void;
  onSelect: (place: PlaceIdentity) => void;
  onBackspace: () => void;
  ariaLabel?: string;
}> = ({ query, selectedIds, inputRef, onQueryChange, onSelect, onBackspace, ariaLabel = '新增目的地，搜索城市或区域' }) => {
  const [candidates, setCandidates] = React.useState<PlaceSearchCandidate[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState('');
  const [anchor, setAnchor] = React.useState<{ top: number; left: number; width: number } | null>(null);
  const rootRef = React.useRef<HTMLDivElement>(null);
  const panelRef = React.useRef<HTMLDivElement>(null);
  const localInputRef = React.useRef<HTMLInputElement | null>(null);
  const composingRef = React.useRef(false);
  const dismissedRef = React.useRef(false);
  const searchSeqRef = React.useRef(0);
  const runner = React.useMemo(() => createPlaceSearchRunner('destination'), []);

  React.useEffect(() => () => runner.cancel(), [runner]);

  React.useEffect(() => {
    dismissedRef.current = false;
  }, [query]);

  const closePanel = React.useCallback(() => {
    dismissedRef.current = true;
    searchSeqRef.current += 1;
    runner.cancel();
    setCandidates([]);
    setError('');
    setLoading(false);
  }, [runner]);

  const search = React.useCallback(async (raw: string) => {
    const next = raw.trim();
    if (next.length < 2 || dismissedRef.current) return;
    const seq = searchSeqRef.current + 1;
    searchSeqRef.current = seq;
    const current = () => seq === searchSeqRef.current && !dismissedRef.current;
    await runner.run(next, {
      setLoading: (value) => { if (current()) setLoading(value); },
      setError: (value) => { if (current()) setError(value); },
      setCandidates: (value) => { if (current()) setCandidates(value); },
    });
  }, [runner]);

  React.useEffect(() => {
    const next = query.trim();
    if (next.length < 2) {
      runner.cancel();
      setCandidates([]);
      setError('');
      setLoading(false);
      return;
    }
    if (dismissedRef.current) return;
    const timer = window.setTimeout(() => void search(next), 280);
    return () => window.clearTimeout(timer);
  }, [query, search, runner]);

  const visible = candidates.filter(({ place }) => !selectedIds.has(place.place_id));
  const open = visible.length > 0 || Boolean(error);

  React.useEffect(() => {
    if (!open) return undefined;
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (rootRef.current?.contains(target) || panelRef.current?.contains(target)) return;
      closePanel();
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      closePanel();
      localInputRef.current?.focus({ preventScroll: true });
    };
    document.addEventListener('pointerdown', handlePointerDown, true);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown, true);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [closePanel, open]);

  React.useEffect(() => {
    if (!open) return undefined;
    const checkHidden = () => {
      const node = rootRef.current;
      if (!node || node.offsetParent === null || getComputedStyle(node).visibility === 'hidden' || node.closest('[aria-hidden="true"]')) {
        closePanel();
      }
    };
    const timer = window.setInterval(checkHidden, 150);
    return () => window.clearInterval(timer);
  }, [closePanel, open]);

  const updateAnchor = React.useCallback(() => {
    const field = localInputRef.current?.closest('.destination-search');
    if (!field) return;
    const rect = field.getBoundingClientRect();
    const width = Math.min(Math.max(rect.width, 280), window.innerWidth - 24);
    const estimatedHeight = Math.min(280, window.innerHeight - 24);
    const below = rect.bottom + 6 + estimatedHeight <= window.innerHeight - 12;
    setAnchor({
      top: below ? rect.bottom + 6 : Math.max(12, rect.top - estimatedHeight - 6),
      left: Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)),
      width,
    });
  }, []);

  React.useLayoutEffect(() => {
    if (!open) {
      setAnchor(null);
      return undefined;
    }
    updateAnchor();
    window.addEventListener('resize', updateAnchor);
    window.addEventListener('scroll', updateAnchor, true);
    return () => {
      window.removeEventListener('resize', updateAnchor);
      window.removeEventListener('scroll', updateAnchor, true);
    };
  }, [open, updateAnchor, visible.length, error]);

  const select = (place: PlaceIdentity) => {
    if (selectedIds.has(place.place_id)) return;
    dismissedRef.current = true;
    searchSeqRef.current += 1;
    runner.cancel();
    setCandidates([]);
    setError('');
    onSelect(place);
  };

  return (
    <div ref={rootRef} className="destination-search" data-testid="destination-search">
      <MapPin size={15} className="destination-search-icon" aria-hidden />
      <input
        ref={(node) => {
          localInputRef.current = node;
          inputRef(node);
        }}
        value={query}
        onChange={(event) => {
          dismissedRef.current = false;
          onQueryChange(event.target.value);
        }}
        onBlur={() => {
          window.setTimeout(() => {
            const active = document.activeElement;
            if (rootRef.current?.contains(active) || panelRef.current?.contains(active)) return;
            closePanel();
          }, 120);
        }}
        onCompositionStart={() => { composingRef.current = true; }}
        onCompositionEnd={() => {
          composingRef.current = false;
          dismissedRef.current = false;
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.preventDefault();
            closePanel();
            return;
          }
          if (event.key === 'Enter') {
            event.preventDefault();
            dismissedRef.current = false;
            void search(query);
            return;
          }
          if (event.key === 'Backspace' && !query && !event.nativeEvent.isComposing && !composingRef.current) {
            event.preventDefault();
            onBackspace();
          }
        }}
        className="destination-search-input"
        placeholder="搜索城市或区域"
        aria-label={ariaLabel}
        autoComplete="off"
      />
      {loading && <span className="destination-search-state" role="status">搜索中…</span>}
      {open && anchor && createPortal(
        <div
          ref={panelRef}
          className="planner-destination-candidates"
          data-testid="destination-candidates"
          style={{ top: anchor.top, left: anchor.left, width: anchor.width }}
        >
          {visible.map(({ place }) => (
            <button
              key={place.place_id}
              type="button"
              onClick={() => select(place)}
              className="planner-destination-candidate"
            >
              <MapPin size={14} className="shrink-0 text-accent" aria-hidden />
              <span className="min-w-0">
                <strong>{place.name}</strong>
                <small>{place.display_name}</small>
              </span>
            </button>
          ))}
          {error && <p role="status" className="planner-destination-candidate-error">{error}</p>}
        </div>,
        document.body,
      )}
    </div>
  );
};

export const DestinationTokenField: React.FC<DestinationTokenFieldProps> = ({ values, queries, onChange, className, onAddStateChange }) => {
  const confirmed = React.useMemo(() => confirmedPlaces(values), [values]);
  const confirmedKey = confirmed.map((place) => place.place_id).join(DRAFT_SEPARATOR);
  const [open, setOpen] = React.useState(() => {
    const drafts = restoredDrafts(values, queries);
    return drafts.length > 0 || confirmed.length === 0;
  });
  const [searchMounted, setSearchMounted] = React.useState(open);
  const [draft, setDraft] = React.useState(() => restoredDrafts(values, queries)[0] ?? '');
  const [draftQueue, setDraftQueue] = React.useState<string[]>(() => restoredDrafts(values, queries).slice(1));
  const [dragFrom, setDragFrom] = React.useState<number | null>(null);
  const [dropIndex, setDropIndex] = React.useState<number | null>(null);
  const [focusSearchTick, setFocusSearchTick] = React.useState(0);
  const [focusAddTick, setFocusAddTick] = React.useState(0);
  const [focusTokenIndex, setFocusTokenIndex] = React.useState<number | null>(null);
  const [sortAnnouncement, setSortAnnouncement] = React.useState('');
  const addRef = React.useRef<HTMLButtonElement>(null);
  const inputRef = React.useRef<HTMLInputElement | null>(null);
  const tokenRefs = React.useRef(new Map<number, HTMLLIElement>());
  const queryKey = queries.join(DRAFT_SEPARATOR);
  const previousConfirmedRef = React.useRef(confirmedKey);
  const emittedConfirmedRef = React.useRef(confirmedKey);
  const emittedQueriesRef = React.useRef(queryKey);
  const dragRef = React.useRef<{
    from: number;
    pointerId: number;
    startX: number;
    startY: number;
    element: HTMLElement;
    dropIndex: number;
    captured: boolean;
    activated: boolean;
    timer: number | null;
  } | null>(null);
  const searchId = React.useId();
  const full = confirmed.length >= MAX_DESTINATIONS;
  const selectedIds = React.useMemo(
    () => new Set(confirmed.map((place) => place.place_id)),
    [confirmed],
  );
  const addState: DestinationAddState = full
    ? 'limit'
    : confirmed.length === 0
      ? 'base'
      : open
        ? 'open'
        : 'closed';
  const addPanelRef = React.useRef<HTMLDivElement>(null);

  React.useLayoutEffect(() => {
    onAddStateChange?.(addState);
  }, [addState, onAddStateChange]);

  React.useLayoutEffect(() => {
    addPanelRef.current?.toggleAttribute('inert', !open);
  }, [open]);

  React.useEffect(() => {
    if (open) {
      setSearchMounted(true);
      return undefined;
    }
    const timer = window.setTimeout(() => setSearchMounted(false), ADD_PANEL_UNMOUNT_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [open]);

  React.useEffect(() => {
    const externalPlaces = previousConfirmedRef.current !== confirmedKey;
    const externalQueries = emittedQueriesRef.current !== queryKey;
    const hasUnconfirmedSlots = values.some((place) => !place);
    if (!externalPlaces && !externalQueries && !hasUnconfirmedSlots) return;
    previousConfirmedRef.current = confirmedKey;
    if (!externalPlaces && !externalQueries) {
      const nextQueries = queriesFor(confirmed, [draft, ...draftQueue], open);
      emittedConfirmedRef.current = confirmedKey;
      emittedQueriesRef.current = nextQueries.join(DRAFT_SEPARATOR);
      onChange(confirmed, nextQueries);
      return;
    }
    const drafts = restoredDrafts(values, queries);
    const nextOpen = drafts.length > 0 || confirmed.length === 0;
    const nextDraft = drafts[0] ?? '';
    setOpen(nextOpen);
    setDraft(nextDraft);
    setDraftQueue(drafts.slice(1));
    emittedConfirmedRef.current = confirmedKey;
    if (hasUnconfirmedSlots) {
      const nextQueries = queriesFor(confirmed, drafts, nextOpen);
      emittedQueriesRef.current = nextQueries.join(DRAFT_SEPARATOR);
      onChange(confirmed, nextQueries);
    } else {
      emittedQueriesRef.current = queryKey;
    }
  }, [confirmed, confirmedKey, draft, draftQueue, onChange, open, queries, queryKey, values]);

  React.useEffect(() => {
    if (focusSearchTick === 0) return;
    inputRef.current?.focus({ preventScroll: true });
    inputRef.current?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [focusSearchTick, open]);

  React.useEffect(() => {
    if (focusAddTick === 0) return;
    addRef.current?.focus({ preventScroll: true });
    addRef.current?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [focusAddTick]);

  React.useEffect(() => {
    if (focusTokenIndex === null) return;
    tokenRefs.current.get(focusTokenIndex)?.focus({ preventScroll: true });
    setFocusTokenIndex(null);
  }, [focusTokenIndex]);

  const emit = (places: PlaceIdentity[], draftText: string, nextOpen: boolean, queue: string[] = draftQueue) => {
    const key = places.map((place) => place.place_id).join(DRAFT_SEPARATOR);
    const nextQueries = queriesFor(places, [draftText, ...queue], nextOpen);
    const queriesKey = nextQueries.join(DRAFT_SEPARATOR);
    const unchanged = key === emittedConfirmedRef.current && queriesKey === emittedQueriesRef.current;
    previousConfirmedRef.current = key;
    // 仅展开/收起且草稿为空时不要重复提交同一份值：上层无需清空校验错误或重复自动保存。
    if (unchanged) return;
    emittedConfirmedRef.current = key;
    emittedQueriesRef.current = queriesKey;
    onChange(places, nextQueries);
  };

  const updateDraft = (next: string) => {
    setDraft(next);
    emit(confirmed, next, true);
  };

  const selectPlace = (place: PlaceIdentity) => {
    if (full || selectedIds.has(place.place_id)) return;
    const next = [...confirmed, place];
    if (next.length >= MAX_DESTINATIONS) {
      setOpen(false);
      setDraft('');
      setDraftQueue([]);
      emit(next, '', false);
      setFocusTokenIndex(next.length - 1);
      return;
    }
    if (next.length === 1 && draftQueue.length === 0) {
      setOpen(false);
      setDraft('');
      emit(next, '', false);
      setFocusAddTick((value) => value + 1);
      return;
    }
    const nextDraft = draftQueue[0] ?? '';
    const remainingDrafts = draftQueue.slice(1);
    setDraft(nextDraft);
    setDraftQueue(remainingDrafts);
    setOpen(true);
    emit(next, nextDraft, true, remainingDrafts);
    setFocusSearchTick((value) => value + 1);
  };

  const toggleOpen = () => {
    if (full) return;
    if (confirmed.length === 0) {
      setFocusSearchTick((value) => value + 1);
      return;
    }
    if (open) {
      setOpen(false);
      setDraft('');
      setDraftQueue([]);
      emit(confirmed, '', false);
      setFocusAddTick((value) => value + 1);
      return;
    }
    setOpen(true);
    setDraft('');
    setDraftQueue([]);
    emit(confirmed, '', true);
    setFocusSearchTick((value) => value + 1);
  };

  const removeAt = (index: number) => {
    const next = confirmed.filter((_, position) => position !== index);
    if (next.length === 0) {
      setOpen(false);
      emit(next, draft, true);
      setFocusSearchTick((value) => value + 1);
      return;
    }
    const nextOpen = open;
    setOpen(nextOpen);
    if (!nextOpen) {
      setDraft('');
      setDraftQueue([]);
    }
    emit(next, nextOpen ? draft : '', nextOpen);
    if (nextOpen) setFocusSearchTick((value) => value + 1);
    else setFocusAddTick((value) => value + 1);
  };

  const removeLastConfirmed = () => {
    if (!confirmed.length) return;
    removeAt(confirmed.length - 1);
  };

  const moveConfirmed = (from: number, to: number) => {
    if (to < 0 || to >= confirmed.length || from === to) return;
    const next = [...confirmed];
    const [place] = next.splice(from, 1);
    next.splice(to, 0, place);
    emit(next, draft, open);
    setFocusTokenIndex(to);
    setSortAnnouncement(`已调整顺序：${next.map((item) => item.name).join('、')}`);
  };

  const releaseCapture = (state: NonNullable<typeof dragRef.current>) => {
    if (!state.captured) return;
    try {
      state.element.releasePointerCapture(state.pointerId);
    } catch {
      // 原生手势之后浏览器可能已经释放了指针捕获。
    }
    state.captured = false;
  };

  const updateDropIndex = (clientX: number, clientY: number) => {
    const state = dragRef.current;
    if (!state) return;
    let best = state.from;
    let bestDistance = Number.POSITIVE_INFINITY;
    for (let index = 0; index < confirmed.length; index += 1) {
      const node = tokenRefs.current.get(index);
      if (!node) continue;
      const rect = node.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      const distance = Math.hypot(clientX - centerX, clientY - centerY);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = index;
      }
    }
    state.dropIndex = best;
    setDropIndex(best);
  };

  const clearPendingTimer = (state: NonNullable<typeof dragRef.current>) => {
    if (state.timer !== null) {
      window.clearTimeout(state.timer);
      state.timer = null;
    }
  };

  const activateDrag = (state: NonNullable<typeof dragRef.current>) => {
    clearPendingTimer(state);
    if (dragRef.current !== state) return;
    state.activated = true;
    try {
      state.element.setPointerCapture(state.pointerId);
      state.captured = true;
    } catch {
      state.captured = false;
    }
    setDragFrom(state.from);
    setDropIndex(state.from);
  };

  const endDrag = (event: React.PointerEvent<HTMLElement>) => {
    const state = dragRef.current;
    if (!state || state.pointerId !== event.pointerId) return;
    clearPendingTimer(state);
    if (state.activated && state.dropIndex !== state.from) moveConfirmed(state.from, state.dropIndex);
    releaseCapture(state);
    dragRef.current = null;
    setDragFrom(null);
    setDropIndex(null);
  };

  const cancelDrag = () => {
    const state = dragRef.current;
    if (state) {
      clearPendingTimer(state);
      releaseCapture(state);
    }
    dragRef.current = null;
    setDragFrom(null);
    setDropIndex(null);
  };

  const startDrag = (event: React.PointerEvent<HTMLElement>, index: number) => {
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    if ((event.target as HTMLElement).closest('button')) return;
    const state = {
      from: index,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      element: event.currentTarget,
      dropIndex: index,
      captured: false,
      activated: false,
      timer: null as number | null,
    };
    dragRef.current = state;
    if (event.pointerType === 'mouse') {
      event.preventDefault();
      activateDrag(state);
      return;
    }
    // 触摸时先等待短按，让普通上下滑动继续滚动页面；按住后再进入排序。
    state.timer = window.setTimeout(() => activateDrag(state), 180);
  };

  const moveDrag = (event: React.PointerEvent<HTMLElement>) => {
    const state = dragRef.current;
    if (!state || state.pointerId !== event.pointerId) return;
    if (!state.activated) {
      if (Math.hypot(event.clientX - state.startX, event.clientY - state.startY) > 8) cancelDrag();
      return;
    }
    event.preventDefault();
    updateDropIndex(event.clientX, event.clientY);
  };

  return (
    <div
      className={cn('destination-token-field', open && !full && confirmed.length > 0 && 'is-open', full && 'is-full', confirmed.length === 0 && 'is-empty', className)}
      data-testid="destination-token-field"
      data-state={full ? 'limit' : confirmed.length === 0 ? 'base' : open ? 'open' : 'closed'}
    >
      <p className="sr-only" role="status" aria-live="polite">{sortAnnouncement}</p>
      <div className="destination-token-flow">
      {confirmed.length === 0 ? (
        <div id={searchId} className="destination-base-search">
          <DestinationSearch
            query={draft}
            selectedIds={selectedIds}
            inputRef={(node) => { inputRef.current = node; }}
            onQueryChange={updateDraft}
            onSelect={selectPlace}
            onBackspace={removeLastConfirmed}
            ariaLabel="目的地，搜索城市或区域"
          />
        </div>
      ) : (
        <ol className="destination-token-list" role="list" aria-label="已选目的地">
          {confirmed.map((place, index) => (
            <li
              key={place.place_id}
              ref={(node) => {
                if (node) tokenRefs.current.set(index, node);
                else tokenRefs.current.delete(index);
              }}
              role="listitem"
              tabIndex={0}
              data-testid={`destination-token-${index}`}
              aria-label={`第 ${index + 1} 站 ${place.name}。按住可拖动排序，也可以用方向键调整顺序，按删除键移除。`}
              className={cn(
                'destination-token',
                dragFrom === index && 'is-dragging',
                dropIndex === index && dragFrom !== null && dragFrom !== index && 'is-drop-target',
              )}
              onPointerDown={(event) => startDrag(event, index)}
              onPointerMove={moveDrag}
              onPointerUp={endDrag}
              onPointerCancel={cancelDrag}
              onLostPointerCapture={() => { if (dragRef.current?.captured) cancelDrag(); }}
              onContextMenu={(event) => { if (dragRef.current?.activated) event.preventDefault(); }}
              onKeyDown={(event) => {
                if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
                  event.preventDefault();
                  moveConfirmed(index, index - 1);
                } else if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
                  event.preventDefault();
                  moveConfirmed(index, index + 1);
                } else if (event.key === 'Delete' || event.key === 'Backspace') {
                  event.preventDefault();
                  removeAt(index);
                }
              }}
            >
              <span className="destination-token-name">{place.name}</span>
              <button
                type="button"
                aria-label={`删除目的地 ${place.name}`}
                className="destination-token-remove"
                onClick={(event) => {
                  event.stopPropagation();
                  removeAt(index);
                }}
              >
                <X size={14} />
              </button>
            </li>
          ))}
        </ol>
      )}
        <div className="destination-token-footer">
          <button
            ref={addRef}
            type="button"
            className="planner-add-destination"
            data-testid="add-destination"
            data-state={full ? 'limit' : confirmed.length === 0 ? 'base' : open ? 'open' : 'closed'}
            aria-expanded={confirmed.length === 0 ? true : open}
            aria-controls={searchId}
            disabled={full}
            onClick={toggleOpen}
          >
            {full ? <Check size={14} aria-hidden /> : open && confirmed.length > 0 ? <X size={14} aria-hidden /> : <Plus size={14} aria-hidden />}
            {full ? '目的地到达上限' : open && confirmed.length > 0 ? '关闭新增' : '新增目的地'}
          </button>
        </div>
      </div>
      {confirmed.length > 0 && !full && (
        <div
          ref={addPanelRef}
          id={searchId}
          data-testid="destination-add-panel"
          className={cn('destination-add-panel', !open && 'is-closed')}
          aria-hidden={!open}
        >
          <div className="destination-add-panel-inner">
            {open ? (
              <DestinationSearch
                query={draft}
                selectedIds={selectedIds}
                inputRef={(node) => { inputRef.current = node; }}
                onQueryChange={updateDraft}
                onSelect={selectPlace}
                onBackspace={removeLastConfirmed}
              />
            ) : searchMounted ? (
              // 收起时用等高占位撑住过渡，搜索框本身立即移出无障碍树和测试查询。
              <div className="destination-add-panel-placeholder" aria-hidden />
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
};
