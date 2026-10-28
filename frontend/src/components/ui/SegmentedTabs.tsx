import React, { useCallback, useLayoutEffect, useRef, useState } from 'react';
import { useReducedMotion } from 'motion/react';
import { cn } from '../../lib/utils';

export interface SegmentedTab<T extends string> {
  id: T;
  label: React.ReactNode;
  testId?: string;
  domId?: string;
  panelId?: string;
}

interface SegmentedTabsProps<T extends string> {
  tabs: ReadonlyArray<SegmentedTab<T>>;
  value: T;
  onChange: (id: T) => void;
  'aria-label': string;
  className?: string;
}

interface IndicatorRect {
  x: number;
  width: number;
  height: number;
}

export function SegmentedTabs<T extends string>({
  tabs,
  value,
  onChange,
  'aria-label': ariaLabel,
  className,
}: SegmentedTabsProps<T>) {
  const reducedMotion = useReducedMotion();
  const groupRef = useRef<HTMLDivElement>(null);
  const buttonRefs = useRef(new Map<T, HTMLButtonElement>());
  const [rect, setRect] = useState<IndicatorRect | null>(null);

  const measure = useCallback(() => {
    const button = buttonRefs.current.get(value);
    if (!button) return;
    const next = { x: button.offsetLeft, width: button.offsetWidth, height: button.offsetHeight };
    setRect((previous) => (
      previous && previous.x === next.x && previous.width === next.width && previous.height === next.height
        ? previous
        : next
    ));
  }, [value]);

  // 字体加载可改变按钮宽度，因此轨道和按钮都需要参与尺寸观察。
  useLayoutEffect(() => {
    measure();
    const group = groupRef.current;
    if (!group || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => measure());
    observer.observe(group);
    buttonRefs.current.forEach((button) => observer.observe(button));
    return () => observer.disconnect();
  }, [measure, tabs.length]);

  const focusAndSelect = (index: number) => {
    const tab = tabs[(index + tabs.length) % tabs.length];
    if (!tab) return;
    onChange(tab.id);
    buttonRefs.current.get(tab.id)?.focus();
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    switch (event.key) {
      case 'ArrowRight':
      case 'ArrowDown':
        event.preventDefault();
        focusAndSelect(index + 1);
        break;
      case 'ArrowLeft':
      case 'ArrowUp':
        event.preventDefault();
        focusAndSelect(index - 1);
        break;
      case 'Home':
        event.preventDefault();
        focusAndSelect(0);
        break;
      case 'End':
        event.preventDefault();
        focusAndSelect(tabs.length - 1);
        break;
      default:
    }
  };

  const indicatorStyle: React.CSSProperties = {
    position: 'absolute',
    top: 4,
    left: 0,
    height: rect?.height ?? 0,
    width: rect?.width ?? 0,
    transform: `translateX(${rect?.x ?? 0}px)`,
    visibility: rect ? 'visible' : 'hidden',
    transition: reducedMotion ? 'none' : 'transform var(--dur-base) var(--ease-decelerate)',
    pointerEvents: 'none',
  };

  return (
    <div ref={groupRef} role="tablist" aria-label={ariaLabel} className={cn('segmented-tabs', className)}>
      <div aria-hidden className="rounded-label border border-stroke/70 bg-panel shadow-sm" style={indicatorStyle} />
      {tabs.map((tab, index) => {
        const selected = tab.id === value;
        return (
          <button
            key={tab.id}
            ref={(node) => {
              if (node) buttonRefs.current.set(tab.id, node);
              else buttonRefs.current.delete(tab.id);
            }}
            type="button"
            role="tab"
            id={tab.domId}
            aria-controls={tab.panelId}
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            data-testid={tab.testId}
            onClick={() => onChange(tab.id)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={cn(
              'relative z-[1] min-h-10 flex-1 whitespace-nowrap rounded-label px-3 py-2 text-[13px] font-medium transition-colors',
              selected ? 'text-accent' : 'text-ink-secondary hover:text-ink',
            )}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
