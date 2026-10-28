import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, m } from 'motion/react';
import type { Variants } from 'motion/react';
import { cn } from '../../lib/utils';
import { duration, transitions } from '../../lib/motion';
import { useOverlayDismiss } from '../../hooks/useOverlayDismiss';


export type PopoverPlacement = 'bottom-start' | 'bottom-end' | 'top-start' | 'top-end';

interface TriggerRenderProps {
  ref: React.Ref<HTMLButtonElement>;
  open: boolean;
  toggle: () => void;
}

export interface PopoverProps {
  trigger: (props: TriggerRenderProps) => React.ReactNode;
  children: React.ReactNode | ((close: () => void) => React.ReactNode);
  placement?: PopoverPlacement;
  offset?: number;
  matchTriggerWidth?: boolean;
  className?: string;
  /* portal 避免面板被祖先的 overflow 裁切。 */
  portal?: boolean;
  testId?: string;
}

const MIN_WIDTH = 320;
const MAX_WIDTH = 360;
const VIEWPORT_MARGIN = 12;

const ORIGIN: Record<PopoverPlacement, string> = {
  'bottom-start': 'top left',
  'bottom-end': 'top right',
  'top-start': 'bottom left',
  'top-end': 'bottom right',
};

interface Position {
  top: number;
  left: number;
  width: number;
  placement: PopoverPlacement;
}

function computePosition(
  triggerRect: DOMRect,
  panelHeight: number,
  preferred: PopoverPlacement,
  offset: number,
  matchTriggerWidth: boolean
): Position {
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  // 宽度不由内容反推，避免测量反馈循环。
  const available = vw - VIEWPORT_MARGIN * 2;
  const width = matchTriggerWidth
    ? Math.min(triggerRect.width, available)
    : available <= MIN_WIDTH
      ? available
      : Math.min(MAX_WIDTH, available);
  const height = panelHeight;

  let vertical: 'top' | 'bottom' = preferred.startsWith('top') ? 'top' : 'bottom';
  let horizontal: 'start' | 'end' = preferred.endsWith('start') ? 'start' : 'end';

  const spaceBelow = vh - triggerRect.bottom - offset;
  const spaceAbove = triggerRect.top - offset;
  if (vertical === 'bottom' && spaceBelow < height && spaceAbove > spaceBelow) {
    vertical = 'top';
  } else if (vertical === 'top' && spaceAbove < height && spaceBelow > spaceAbove) {
    vertical = 'bottom';
  }

  let left = horizontal === 'start' ? triggerRect.left : triggerRect.right - width;
  if (horizontal === 'start' && left + width > vw - VIEWPORT_MARGIN) {
    horizontal = 'end';
    left = triggerRect.right - width;
  } else if (horizontal === 'end' && left < VIEWPORT_MARGIN) {
    horizontal = 'start';
    left = triggerRect.left;
  }
  left = Math.min(Math.max(left, VIEWPORT_MARGIN), vw - width - VIEWPORT_MARGIN);

  const top =
    vertical === 'bottom'
      ? triggerRect.bottom + offset
      : triggerRect.top - offset - height;

  return { top, left, width, placement: `${vertical}-${horizontal}` as PopoverPlacement };
}

export const Popover: React.FC<PopoverProps> = ({
  trigger,
  children,
  placement = 'bottom-start',
  offset = 8,
  matchTriggerWidth = false,
  className,
  portal = false,
  testId,
}) => {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<Position | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const close = useCallback(() => setOpen(false), []);
  const toggle = useCallback(() => setOpen((v) => !v), []);

  const reposition = useCallback(() => {
    const t = triggerRef.current;
    const p = panelRef.current;
    if (!t || !p) return;
    const triggerRect = t.getBoundingClientRect();
    setPosition(computePosition(triggerRect, p.offsetHeight, placement, offset, matchTriggerWidth));
  }, [placement, offset, matchTriggerWidth]);

  useLayoutEffect(() => {
    if (!open) {
      // 保留关闭前的位置，让退出动画仍锚定在触发器旁。
      return undefined;
    }
    reposition();
    window.addEventListener('resize', reposition);
    window.addEventListener('scroll', reposition, true);
    return () => {
      window.removeEventListener('resize', reposition);
      window.removeEventListener('scroll', reposition, true);
    };
  }, [open, reposition]);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as Node;
      if (panelRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      close();
    };
    document.addEventListener('pointerdown', onPointerDown, true);
    return () => document.removeEventListener('pointerdown', onPointerDown, true);
  }, [open, close]);

  /* 非模态浮层不传 panelRef，打开时焦点留在触发器。 */
  useOverlayDismiss({ open, onDismiss: close });

  const resolvedPlacement = position?.placement ?? placement;

  const closedOffset = resolvedPlacement.startsWith('bottom') ? -4 : 4;
  const panelVariants: Variants = {
    hidden: { opacity: 0, scale: 0.97, y: closedOffset },
    visible: {
      opacity: 1,
      scale: 1,
      y: 0,
      transition: transitions.enter(duration.base),
    },
    exit: {
      opacity: 0,
      scale: 0.98,
      y: closedOffset,
      transition: transitions.exit(duration.fast),
    },
  };

  const panel = (
    <AnimatePresence>
      {open && (
        <m.div
          key="popover-panel"
          ref={panelRef}
          data-testid={testId}
          className={cn('fixed rounded-card border border-stroke bg-panel', className)}
          style={{
            zIndex: 1200,
            top: position?.top ?? 0,
            left: position?.left ?? 0,
            width: position?.width ?? MIN_WIDTH,
            transformOrigin: ORIGIN[resolvedPlacement],
            boxShadow: 'var(--shadow-md)',
            // 定位完成前隐藏，避免首帧闪现在视口原点。
            visibility: position ? 'visible' : 'hidden',
          }}
          variants={panelVariants}
          initial="hidden"
          animate="visible"
          exit="exit"
        >
          {typeof children === 'function' ? children(close) : children}
        </m.div>
      )}
    </AnimatePresence>
  );

  return (
    <>
      {trigger({
        ref: triggerRef,
        open,
        toggle,
      })}
      {portal && typeof document !== 'undefined'
        ? createPortal(panel, document.body)
        : panel}
    </>
  );
};
