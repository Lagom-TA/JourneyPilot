import { CalendarDays, ChevronLeft, ChevronRight, X } from "lucide-react";
import { cn } from "../../../../lib/utils";
import { FIELD_LABEL, FIELD_VALUE, RULED_FIELD } from "../../../../components/ui/Input";
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
export const DateRangePicker: React.FC<{
    start: string;
    end: string;
    onChange: (start: string, end: string) => void;
}> = ({ start, end, onChange }) => {
    const [open, setOpen] = React.useState(false);
    const [visibleMonth, setVisibleMonth] = React.useState(() => fromIso(start) || new Date());
    const closeRef = React.useRef<HTMLButtonElement>(null);
    const rootRef = React.useRef<HTMLDivElement>(null);
    const days = daysBetween(start, end);
    React.useEffect(() => {
        if (!open)
            return undefined;
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape')
                setOpen(false);
        };
        const onPointerDown = (event: MouseEvent) => {
            if (rootRef.current && !rootRef.current.contains(event.target as Node))
                setOpen(false);
        };
        document.addEventListener('keydown', onKeyDown);
        document.addEventListener('mousedown', onPointerDown);
        window.setTimeout(() => closeRef.current?.focus(), 0);
        return () => {
            document.removeEventListener('keydown', onKeyDown);
            document.removeEventListener('mousedown', onPointerDown);
        };
    }, [open]);
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
      <button type="button" aria-haspopup="dialog" aria-expanded={open} aria-label={`${start || '选择开始日期'} → ${end || '选择结束日期'}${days > 0 ? ` · ${days} 天 ${days - 1} 晚` : ''}`} onClick={() => setOpen(true)} className={cn(RULED_FIELD, 'text-left')}>
        <CalendarDays size={17} className="shrink-0 text-chart"/>
        <span className={cn('min-w-0 flex-1 truncate', FIELD_VALUE)}>
          {start || '选择开始日期'} <span className="text-chart">→</span> {end || '选择结束日期'}
        </span>
      </button>

      {open && (<div className="fixed inset-0 z-50 flex items-end bg-ink/25 sm:absolute sm:inset-auto sm:left-0 sm:top-[calc(100%+8px)] sm:w-[680px] sm:items-start sm:bg-transparent" onMouseDown={(event) => { if (event.currentTarget === event.target)
            setOpen(false); }}>
          <div role="dialog" aria-modal="true" aria-label="选择旅行日期" className="max-h-[85vh] w-full overflow-y-auto rounded-t-card border border-stroke bg-panel p-4 shadow-lg sm:rounded-card sm:p-5">
            <div className="mb-4 flex items-center justify-between">
              <button type="button" aria-label="上个月" onClick={() => setVisibleMonth((value) => addMonths(value, -1))} className="grid h-10 w-10 place-items-center rounded-card hover:bg-surface"><ChevronLeft size={17}/></button>
              <p className="text-xs text-ink-secondary">最长 14 天</p>
              <div className="flex items-center gap-1">
                <button type="button" aria-label="下个月" onClick={() => setVisibleMonth((value) => addMonths(value, 1))} className="grid h-10 w-10 place-items-center rounded-card hover:bg-surface"><ChevronRight size={17}/></button>
                <button ref={closeRef} type="button" aria-label="关闭日期选择" onClick={() => setOpen(false)} className="grid h-10 w-10 place-items-center rounded-card hover:bg-surface"><X size={17}/></button>
              </div>
            </div>
            <div className="flex gap-8">
              <Month month={visibleMonth} start={start} end={end} onSelect={select}/>
              <div className="hidden flex-1 sm:block"><Month month={addMonths(visibleMonth, 1)} start={start} end={end} onSelect={select}/></div>
            </div>
            <div className="mt-4 flex items-center justify-between border-t border-stroke pt-4">
              <button type="button" onClick={() => onChange('', '')} className="min-h-10 text-sm text-ink-secondary hover:text-ink">清除日期</button>
              <button type="button" disabled={!start || !end} onClick={() => setOpen(false)} className="min-h-10 rounded-card bg-accent px-4 text-sm font-semibold text-white disabled:opacity-40">确认日期{days > 0 ? ` · ${days} 天 ${days - 1} 晚` : ''}</button>
            </div>
          </div>
        </div>)}
    </div>);
};
