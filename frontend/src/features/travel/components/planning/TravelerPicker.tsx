import { AnimatePresence, m, useReducedMotion } from 'motion/react';
import { ChevronDown, X } from 'lucide-react';
import React from 'react';
import { createPortal } from 'react-dom';
import { useIsCompactViewport } from '../../../../hooks/useMediaQuery';
import { useOverlayDismiss } from '../../../../hooks/useOverlayDismiss';
import { duration, easing } from '../../../../lib/motion';
import '../../../../styles/traveler-picker.css';

const ADULT_OPTIONS = Array.from({ length: 9 }, (_, index) => index + 1);
const CHILD_OPTIONS = Array.from({ length: 10 }, (_, index) => index);
const MAX_COUNT = 20;

interface CountDraft {
  selected: number | null;
  custom: string;
}

function countDraft(value: number, options: number[]): CountDraft {
  return options.includes(value) ? { selected: value, custom: '' } : { selected: null, custom: String(value) };
}

function countValue(draft: CountDraft, minimum: number): number | null {
  if (draft.selected !== null) return draft.selected;
  if (!/^\d+$/.test(draft.custom)) return null;
  const value = Number(draft.custom);
  return Number.isInteger(value) && value >= minimum && value <= MAX_COUNT ? value : null;
}

const CountChoices: React.FC<{
  label: '成人' | '儿童';
  options: number[];
  draft: CountDraft;
  minimum: number;
  onChange: (draft: CountDraft) => void;
}> = ({ label, options, draft, minimum, onChange }) => {
  const customActive = draft.selected === null;
  const customInvalid = customActive && countValue(draft, minimum) === null;
  return (
    <section className="traveler-picker-group" role="group" aria-label={label}>
      <h3>{label}</h3>
      <div className="traveler-picker-options">
        {options.map((count) => (
          <button
            key={count}
            type="button"
            aria-label={`${count} 位${label}`}
            aria-pressed={draft.selected === count}
            onClick={() => onChange({ selected: count, custom: '' })}
          >{count}</button>
        ))}
        <input
          className="traveler-picker-custom"
          type="text"
          inputMode="numeric"
          autoComplete="off"
          aria-label={`自填${label}`}
          aria-invalid={customInvalid || undefined}
          data-active={customActive || undefined}
          value={draft.custom}
          placeholder="自填"
          onChange={(event) => onChange({ selected: null, custom: event.target.value })}
        />
      </div>
    </section>
  );
};

interface AnchorPosition {
  top: number;
  left: number;
  width: number;
  above: boolean;
}

export const TravelerPicker: React.FC<{
  adults: number;
  childrenCount: number;
  onChange: (adults: number, children: number) => void;
}> = ({ adults, childrenCount, onChange }) => {
  const [open, setOpen] = React.useState(false);
  const [adultDraft, setAdultDraft] = React.useState(() => countDraft(adults, ADULT_OPTIONS));
  const [childDraft, setChildDraft] = React.useState(() => countDraft(childrenCount, CHILD_OPTIONS));
  const [anchor, setAnchor] = React.useState<AnchorPosition | null>(null);
  const triggerRef = React.useRef<HTMLButtonElement>(null);
  const panelRef = React.useRef<HTMLDivElement>(null);
  const panelId = React.useId();
  const isCompact = useIsCompactViewport();
  const reducedMotion = useReducedMotion();
  const close = React.useCallback(() => setOpen(false), []);
  const nextAdults = countValue(adultDraft, 1);
  const nextChildren = countValue(childDraft, 0);
  const valid = nextAdults !== null && nextChildren !== null;
  const summary = childrenCount > 0 ? `${adults} 成人 · ${childrenCount} 儿童` : `${adults} 人`;

  const updateAnchor = React.useCallback(() => {
    const trigger = triggerRef.current?.getBoundingClientRect();
    if (!trigger) return;
    const width = Math.min(600, window.innerWidth - 24);
    const height = Math.min(panelRef.current?.offsetHeight ?? 320, window.innerHeight - 24);
    const below = window.innerHeight - trigger.bottom - 8;
    const above = below < height && trigger.top > below;
    const top = Math.max(12, Math.min(above ? trigger.top - height - 8 : trigger.bottom + 8, window.innerHeight - height - 12));
    const left = Math.max(12, Math.min(trigger.left, window.innerWidth - width - 12));
    setAnchor({ top, left, width, above });
  }, []);

  React.useLayoutEffect(() => {
    if (!open || isCompact) return undefined;
    updateAnchor();
    window.addEventListener('resize', updateAnchor);
    window.addEventListener('scroll', updateAnchor, true);
    const observer = new ResizeObserver(updateAnchor);
    if (panelRef.current) observer.observe(panelRef.current);
    return () => {
      window.removeEventListener('resize', updateAnchor);
      window.removeEventListener('scroll', updateAnchor, true);
      observer.disconnect();
    };
  }, [isCompact, open, updateAnchor]);

  React.useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!panelRef.current?.contains(target) && !triggerRef.current?.contains(target)) close();
    };
    document.addEventListener('pointerdown', onPointerDown, true);
    return () => document.removeEventListener('pointerdown', onPointerDown, true);
  }, [close, open]);

  useOverlayDismiss({ open, onDismiss: close, panelRef, trapFocus: isCompact });

  const toggle = () => {
    if (open) {
      close();
      return;
    }
    setAdultDraft(countDraft(adults, ADULT_OPTIONS));
    setChildDraft(countDraft(childrenCount, CHILD_OPTIONS));
    setAnchor(null);
    setOpen(true);
  };

  return (
    <div className="traveler-picker">
      <span className="planner-field-label">同行人数</span>
      <button
        ref={triggerRef}
        type="button"
        className="planner-field-control traveler-picker-trigger"
        data-testid="traveler-picker-trigger"
        data-with-children={childrenCount > 0 || undefined}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        aria-label={`同行人数：${adults} 位成人，${childrenCount} 位儿童`}
        onClick={toggle}
      >
        <span>{summary}</span>
        <ChevronDown size={16} aria-hidden="true" />
      </button>
      {createPortal(
        <AnimatePresence>
          {open && (
            <div
              className={`traveler-picker-layer${isCompact ? ' is-compact' : ''}`}
              style={isCompact ? undefined : { top: anchor?.top ?? 0, left: anchor?.left ?? 0, width: anchor?.width ?? 600, visibility: anchor ? 'visible' : 'hidden' }}
            >
              {isCompact && <button type="button" className="traveler-picker-backdrop" tabIndex={-1} aria-hidden="true" onClick={close} />}
              <m.div
                ref={panelRef}
                id={panelId}
                role="dialog"
                aria-label="选择同行人数"
                aria-modal={isCompact || undefined}
                tabIndex={-1}
                data-testid="traveler-picker-dialog"
                className="traveler-picker-panel"
                style={{ transformOrigin: `${anchor?.above ? 'bottom' : 'top'} left` }}
                initial={reducedMotion ? false : { opacity: 0, y: isCompact ? 28 : 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: reducedMotion ? 0 : isCompact ? 28 : 4 }}
                transition={{ duration: reducedMotion ? 0 : duration.base, ease: easing.decelerate }}
              >
                <header className="traveler-picker-header">
                  <h2>同行人数</h2>
                  <button type="button" aria-label="关闭人数选择" onClick={close}><X size={18} aria-hidden="true" /></button>
                </header>
                <CountChoices label="成人" options={ADULT_OPTIONS} draft={adultDraft} minimum={1} onChange={setAdultDraft} />
                <CountChoices label="儿童" options={CHILD_OPTIONS} draft={childDraft} minimum={0} onChange={setChildDraft} />
                <footer className="traveler-picker-footer">
                  <button type="button" className="traveler-picker-cancel" onClick={close}>取消</button>
                  <button
                    type="button"
                    className="traveler-picker-done"
                    disabled={!valid}
                    onClick={() => {
                      if (nextAdults === null || nextChildren === null) return;
                      onChange(nextAdults, nextChildren);
                      close();
                    }}
                  >完成</button>
                </footer>
              </m.div>
            </div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </div>
  );
};
