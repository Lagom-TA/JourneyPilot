import React, { useCallback, useLayoutEffect, useRef, useState } from 'react';
import { Liquid } from 'liquid-gooey';
import { useReducedMotion } from 'motion/react';
import { cn } from '../../lib/utils';

export interface SegmentedTab<T extends string> {
  id: T;
  label: React.ReactNode;
  /** 透传给 `<button role="tab">`，e2e 判据按它找。 */
  testId?: string;
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

/**
 * 分段页签（segmented control）：一条 `bg-surface` 轨道，选中项底下一枚 `bg-panel` 的浅托。
 *
 * ── 托是**一枚**在两项之间流动的液体，不是每项各自开关的底色 ──────────────────────
 * 以前选中态写在按钮自己身上（`bg-panel shadow-sm`），切换时旧的瞬灭、新的瞬现，两个
 * 位置之间没有任何东西告诉你「同一个选择移到了那边」。现在托由 `liquid-gooey` 的
 * `move` 效果画：一枚透明的定位元素按选中项的几何走 `--dur-base` 位移，液面拖着一点
 * 尾巴追上去，落位时收成静止的矩形。文字、焦点环、命中区都在液面之上的真实 DOM 里，
 * 库只画那层轮廓（`fill` = 面板色、`shadow` = `--shadow-sm`，两个都是登记过的 token）。
 *
 * ── 调校取「精确的仪器」那一端 ────────────────────────────────────────────────────
 * 库的默认手感是果冻（wobble 0.5 / trail 0.575）。产品是「打理得当的旅行制图桌」，
 * 所以 springiness 抬到 0.8（紧跟，不拖泥）、wobble 压到 0.15（落位几乎不回弹）、
 * trail 0.35（尾巴看得见、但短）。`blur` 只有 3：只有一枚托，不需要桥接，blur 大了
 * 4px 圆角的小矩形会被滤镜磨成药丸。
 *
 * ── `prefers-reduced-motion` 走另一条渲染路径 ───────────────────────────────────
 * reduce 之下不挂 `Liquid`：直接渲染一枚 `bg-panel shadow-sm` 的静态托，位置照旧按
 * 选中项算。全局那块 reduce CSS 会把它的 transform 过渡压成 1ms，等于瞬移 —— 与产品
 * 其它位置的 reduce 行为一致（不位移，可以出现）。读法用动效库的 `useReducedMotion()`
 * 而不是自己 `matchMedia`，理由与 `BundleMapLeaflet` 同一处注释。
 *
 * ── 键盘按 WAI-ARIA tabs 模式 ────────────────────────────────────────────────────
 * roving tabindex：只有选中项在 Tab 序列里，← → Home End 在项间移动并**立即选中**
 * （自动激活模式 —— 两个页签之间切换没有代价，不需要手动激活那一步）。
 */
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

  /* 选中项变了就量一次；字体晚到、容器换宽也要重量 —— 观察整条轨道即可，
     任何一项的宽度变化都会改变轨道内的布局。 */
  useLayoutEffect(() => {
    measure();
    const group = groupRef.current;
    if (!group || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => measure());
    observer.observe(group);
    return () => observer.disconnect();
  }, [measure, tabs.length]);

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

  const trackClass = cn('relative flex min-w-0 items-center rounded-card bg-surface p-1', className);

  /* 托的几何：`top` 对齐轨道内边距（p-1 = 4px），x / width 跟选中项。第一次量到之前
     `visibility: hidden`，useLayoutEffect 在绘制前就量完，用户看不到那一帧。
     **只过渡 transform**：width 直接落位（动 width 是 layout 动画）。液体路径上这不
     可见 —— 液面按自己的弹簧追矩形，宽度的跳变被它抹平；reduce 路径上本来就是瞬移。 */
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
        aria-selected={selected}
        tabIndex={selected ? 0 : -1}
        data-testid={tab.testId}
        onClick={() => onChange(tab.id)}
        onKeyDown={(event) => onKeyDown(event, index)}
        className={cn(
          'relative z-[1] rounded-label px-3 py-1.5 text-xs font-semibold transition-colors',
          selected ? 'text-ink' : 'text-ink-secondary hover:text-ink'
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
