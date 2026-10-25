import React, { useCallback, useLayoutEffect, useRef, useState } from 'react';
import { Liquid } from 'liquid-gooey';
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
    setRect((previous) => {
      const next = { x: button.offsetLeft, width: button.offsetWidth, height: button.offsetHeight };
      if (previous && previous.x === next.x && previous.width === next.width && previous.height === next.height) {
        return previous;
      }
      return next;
    });
  }, [value]);

  // 字体加载可改变按钮宽度而不改变轨道宽度，因此同时观察按钮。
  useLayoutEffect(() => {
    measure();
    const group = groupRef.current;
    if (!group || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => measure());
    observer.observe(group);
    buttonRefs.current.forEach((button) => observer.observe(button));
    return () => observer.disconnect();
  }, [measure, tabs.length, reducedMotion]);

  const focusAndSelect = (index: number) => {
    const wrapped = (index + tabs.length) % tabs.length;
    const tab = tabs[wrapped];
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

  const trackClass = cn('relative isolate flex min-w-0 items-center rounded-card bg-surface/65 p-1', className);

  /* 宽度直接落位，只过渡 transform，避免布局动画。 */
  const indicatorStyle: React.CSSProperties = {
    position: 'absolute',
    top: 4,
    left: 0,
    height: rect?.height ?? 0,
    width: rect?.width ?? 0,
    transform: `translateX(${rect?.x ?? 0}px)`,
    visibility: rect ? 'visible' : 'hidden',
    transition: 'transform var(--dur-base) var(--ease-standard)',
    pointerEvents: 'none',
  };

  const buttons = tabs.map((tab, index) => {
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
          'relative z-[1] min-h-10 whitespace-nowrap rounded-label px-3 py-2 text-xs font-semibold transition-colors',
          selected ? 'text-accent' : 'text-ink-secondary hover:text-ink'
        )}
      >
        {tab.label}
      </button>
    );
  });

  if (reducedMotion) {
    return (
      <div ref={groupRef} role="tablist" aria-label={ariaLabel} className={trackClass}>
        <div aria-hidden className="rounded-label bg-panel shadow-sm" style={indicatorStyle} />
        {buttons}
      </div>
    );
  }

  return (
    <Liquid
      ref={groupRef}
      role="tablist"
      aria-label={ariaLabel}
      className={trackClass}
      fill="var(--color-panel)"
      shadow="var(--shadow-sm)"
      blur={3}
      contrast={18}
      filterPadding={8}
    >
      <Liquid.Item effect="move" move={{ springiness: 0.8, wobble: 0.15, stretch: 0.3, trail: 0.35 }}>
        <div aria-hidden className="rounded-label" style={indicatorStyle} />
      </Liquid.Item>
      {buttons}
    </Liquid>
  );
}
