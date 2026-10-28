import { CalendarDays, ChevronLeft, ChevronRight, X } from "lucide-react";
import { AnimatePresence, m } from "motion/react";
import { createPortal } from "react-dom";
import { cn } from "../../../../lib/utils";
import { FIELD_LABEL, FIELD_VALUE, RULED_FIELD } from "../../../../components/ui/Input";
import { useOverlayDismiss } from "../../../../hooks/useOverlayDismiss";
import { useIsCompactViewport } from "../../../../hooks/useMediaQuery";
import { duration, easing } from "../../../../lib/motion";
import React from 'react';
const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];
function iso(date: Date): string {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}
function fromIso(value: string): Date | null {
    if (!value)
        return null;
    const [year, month, day] = value.split('-').map(Number);
    return new Date(year, month - 1, day);
}
function addMonths(date: Date, amount: number): Date {
    return new Date(date.getFullYear(), date.getMonth() + amount, 1);
}
function daysBetween(start: string, end: string): number {
    const left = fromIso(start);
    const right = fromIso(end);
    if (!left || !right)
        return 0;
    return Math.floor((right.getTime() - left.getTime()) / 86400000) + 1;
}
const Month: React.FC<{
    month: Date;
    start: string;
    end: string;
    onSelect: (value: string) => void;
}> = ({ month, start, end, onSelect }) => {
    const first = new Date(month.getFullYear(), month.getMonth(), 1);
    const count = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
    const cells: Array<number | null> = Array(first.getDay()).fill(null);
    for (let day = 1; day <= count; day += 1)
        cells.push(day);
    while (cells.length % 7)
        cells.push(null);
    return (<section className="min-w-0 flex-1" aria-label={`${month.getFullYear()}年${month.getMonth() + 1}月`}>
      <h3 className="mb-3 text-center text-sm font-semibold text-ink">{month.getFullYear()} 年 {month.getMonth() + 1} 月</h3>
      <div className="grid grid-cols-7 gap-1">
        {WEEKDAYS.map((item) => <span key={item} className="py-1 text-center text-[11px] text-ink-secondary">{item}</span>)}
        {cells.map((day, index) => {
            if (!day)
                return <span key={`blank-${index}`}/>;
            const value = iso(new Date(month.getFullYear(), month.getMonth(), day));
            const isStart = value === start;
            const isEnd = value === end && value !== start;
            const selected = isStart || isEnd;
            const inRange = Boolean(start && end && value > start && value < end);
            const caption = isStart ? '出发' : isEnd ? '返程' : '';
            return (<button key={value} type="button" aria-label={`选择 ${value}${caption ? `（${caption}）` : ''}`} aria-pressed={selected} onClick={() => onSelect(value)} className={cn('flex aspect-square min-h-9 flex-col items-center justify-center rounded-card text-sm transition-colors', selected && 'bg-accent font-semibold text-white', inRange && 'bg-accent-soft text-accent', !selected && !inRange && 'text-ink hover:bg-surface')}>

              {caption && <span className="pointer-events-none -mt-0.5 mb-px text-xs font-semibold leading-none text-white">{caption}</span>}
              <span className="leading-none">{day}</span>
            </button>);
        })}
      </div>
    </section>);
};
interface AnchorPosition {
    top: number;
    left: number;
    width: number;
    side: 'top' | 'bottom';
}
export const DateRangePicker: React.FC<{
    start: string;
    end: string;
    onChange: (start: string, end: string) => void;
}> = ({ start, end, onChange }) => {
    const [open, setOpen] = React.useState(false);
    const [visibleMonth, setVisibleMonth] = React.useState(() => fromIso(start) || new Date());
    const rootRef = React.useRef<HTMLDivElement>(null);
    const triggerRef = React.useRef<HTMLButtonElement>(null);
    const panelRef = React.useRef<HTMLDivElement>(null);
    const [anchor, setAnchor] = React.useState<AnchorPosition | null>(null);
    const isCompact = useIsCompactViewport();
    const close = React.useCallback(() => setOpen(false), []);
    const days = daysBetween(start, end);
    const updateAnchor = React.useCallback(() => {
        const trigger = triggerRef.current?.getBoundingClientRect();
        if (!trigger) return;
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;
        const width = Math.min(680, viewportWidth - 24);
        const height = Math.min(panelRef.current?.offsetHeight ?? 400, viewportHeight - 24);
        const side = trigger.bottom + 8 + height <= viewportHeight - 12 || trigger.top - height - 8 < 12 ? 'bottom' : 'top';
        const unclampedTop = side === 'bottom' ? trigger.bottom + 8 : trigger.top - height - 8;
        const top = Math.max(12, Math.min(unclampedTop, viewportHeight - height - 12));
        const left = Math.max(12, Math.min(trigger.left, viewportWidth - width - 12));
        setAnchor({ top, left, width, side });
    }, []);
    React.useLayoutEffect(() => {
        if (!open) return undefined;
        if (isCompact) {
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
    }, [isCompact, open, updateAnchor]);
    React.useEffect(() => {
        if (!open)
            return undefined;
        const onPointerDown = (event: MouseEvent) => {
            const target = event.target as Node;
            if (rootRef.current?.contains(target) || panelRef.current?.contains(target)) return;
            close();
        };
        document.addEventListener('mousedown', onPointerDown);
        return () => {
            document.removeEventListener('mousedown', onPointerDown);
        };
    }, [close, open]);
    useOverlayDismiss({ open, onDismiss: close, panelRef });
    const select = (value: string) => {
        if (!start || end || value < start) {
            onChange(value, '');
            return;
        }
        if (daysBetween(start, value) > 14) {
            onChange(value, '');
            return;
        }
        onChange(start, value);
    };
    return (<div ref={rootRef} className="relative min-w-0 flex-1">


      <div className="mb-1 flex items-baseline gap-2">
        <label className={cn(FIELD_LABEL, 'mb-0')}>精确日期</label>


        <span className="shrink-0 text-[11px] font-medium text-ink-muted">
          {days > 0 ? `${days} 天 ${days - 1} 晚` : '最长 14 天'}
        </span>
      </div>
      <button ref={triggerRef} type="button" data-testid="date-range-trigger" aria-haspopup="dialog" aria-expanded={open} aria-label={`${start || '选择开始日期'} → ${end || '选择结束日期'}${days > 0 ? ` · ${days} 天 ${days - 1} 晚` : ''}`} onClick={() => setOpen(true)} className={cn(RULED_FIELD, 'text-left')}>
        <CalendarDays size={17} className="shrink-0 text-chart"/>
        <span className={cn('min-w-0 flex-1 truncate', FIELD_VALUE)}>
          {start || '选择开始日期'} <span className="text-chart">→</span> {end || '选择结束日期'}
        </span>
      </button>

      {createPortal(<AnimatePresence>
        {open && (
          <div
            className={isCompact ? 'fixed inset-0 flex items-end' : 'fixed'}
            style={isCompact
              ? { zIndex: 1200 }
              : { zIndex: 1200, top: anchor?.top ?? 0, left: anchor?.left ?? 0, width: anchor?.width ?? 680, visibility: anchor ? 'visible' : 'hidden' }}
          >
            <m.button
              type="button"
              aria-hidden="true"
              tabIndex={-1}
              className="absolute inset-0 cursor-default bg-ink/25 sm:hidden"
              onClick={close}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: duration.fast, ease: easing.standard }}
            />
            <m.div
              ref={panelRef}
              tabIndex={-1}
              role="dialog"
              aria-modal={isCompact || undefined}
              aria-label="选择旅行日期"
              data-testid="date-range-dialog"
              className="relative max-h-[85vh] w-full overflow-y-auto rounded-t-card border border-stroke bg-panel p-4 shadow-lg sm:rounded-card sm:p-5"
              style={{ transformOrigin: `${anchor?.side === 'top' ? 'bottom' : 'top'} left` }}
              initial={isCompact ? { opacity: 0, y: '100%' } : { opacity: 0, y: anchor?.side === 'top' ? 6 : -6, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1, transition: { duration: isCompact ? duration.slow : duration.base, ease: easing.decelerate } }}
              exit={isCompact
                ? { opacity: 0, y: '100%', transition: { duration: duration.base, ease: easing.accelerate } }
                : { opacity: 0, y: anchor?.side === 'top' ? 4 : -4, scale: 0.98, transition: { duration: duration.fast, ease: easing.accelerate } }}
            >
              <div className="mb-4 flex items-center justify-between">
                <button type="button" aria-label="上个月" onClick={() => setVisibleMonth((value) => addMonths(value, -1))} className="grid h-10 w-10 place-items-center rounded-card hover:bg-surface"><ChevronLeft size={17}/></button>
                <p className="text-xs text-ink-secondary">最长 14 天</p>
                <div className="flex items-center gap-1">
                  <button type="button" aria-label="下个月" onClick={() => setVisibleMonth((value) => addMonths(value, 1))} className="grid h-10 w-10 place-items-center rounded-card hover:bg-surface"><ChevronRight size={17}/></button>
                  <button type="button" aria-label="关闭日期选择" onClick={close} className="grid h-10 w-10 place-items-center rounded-card hover:bg-surface"><X size={17}/></button>
                </div>
              </div>
              <div className="flex gap-8">
                <Month month={visibleMonth} start={start} end={end} onSelect={select}/>
                <div className="hidden flex-1 sm:block"><Month month={addMonths(visibleMonth, 1)} start={start} end={end} onSelect={select}/></div>
              </div>
              <div className="mt-4 flex items-center justify-between border-t border-stroke pt-4">
                <button type="button" onClick={() => onChange('', '')} className="min-h-10 text-sm text-ink-secondary hover:text-ink">清除日期</button>
                <button type="button" disabled={!start || !end} onClick={close} className="min-h-10 rounded-card bg-accent px-4 text-sm font-semibold text-white disabled:opacity-40">确认日期{days > 0 ? ` · ${days} 天 ${days - 1} 晚` : ''}</button>
              </div>
            </m.div>
          </div>
        )}
      </AnimatePresence>, document.body)}
    </div>);
};
