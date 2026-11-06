import React, { useCallback, useEffect, useRef, useState } from 'react';
import type { PanInfo } from 'motion/react';
import { AnimatePresence, animate, m, useDragControls, useMotionValue, useReducedMotion } from 'motion/react';
import { cn } from '../../lib/utils';
import { duration, easing, spring } from '../../lib/motion';
import { CanvasMotion } from './CanvasMotion';
import { useOverlayDismiss } from '../../hooks/useOverlayDismiss';
import { releaseSheet, sheetOffset, type SheetDetent } from '../../lib/sheetDetents';

/* 拖拽需要 domMax，由 CanvasMotion 异步加载。 */

export type { SheetDetent } from '../../lib/sheetDetents';

interface SheetProps {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  initialDetent?: SheetDetent;
  testId?: string;
}

function useViewportHeight(): number {
  const [vh, setVh] = useState(() => (typeof window === 'undefined' ? 800 : window.innerHeight));
  useEffect(() => {
    const update = () => setVh(window.innerHeight);
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);
  return vh;
}

export const Sheet: React.FC<SheetProps> = ({
  open,
  onClose,
  children,
  initialDetent = 55,
  testId = 'sheet',
}) => {
  const vh = useViewportHeight();
  // 面板固定最大高度，使停靠切换与拖拽只改变 transform。
  const panelHeight = Math.round(vh * 0.92);
  const yFor = useCallback(
    (detent: SheetDetent) => sheetOffset(panelHeight, detent),
    [panelHeight]
  );
  const closedY = panelHeight;

  const [detent, setDetent] = useState<SheetDetent>(initialDetent);
  const [entered, setEntered] = useState(false);
  const y = useMotionValue(closedY);
  const reducedMotion = useReducedMotion();
  const dragControls = useDragControls();
  // 拖拽结束后的 click 不能再次切换停靠位置。
  const draggedRef = useRef(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useOverlayDismiss({ open, onDismiss: onClose, panelRef, trapFocus: true });

  useEffect(() => {
    if (open) {
      setDetent(initialDetent);
      setEntered(false);
    }
  }, [open, initialDetent]);

  const snapTo = useCallback(
    (target: SheetDetent) => {
      if (target === detent) {
        // 目标停靠位未变时声明式动画不会重跑，需命令式吸附。
        if (reducedMotion) y.set(yFor(target));
        else animate(y, yFor(target), spring);
      } else {
        setDetent(target);
      }
    },
    [detent, reducedMotion, y, yFor]
  );

  const handleDragEnd = useCallback(
    (_event: MouseEvent | TouchEvent | PointerEvent, info: PanInfo) => {
      const target = releaseSheet(panelHeight, y.get(), info.velocity.y, detent);
      if (target === 0) onClose();
      else snapTo(target);
    },
    [detent, onClose, panelHeight, snapTo, y]
  );

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0" style={{ zIndex: 'var(--z-sheet)' }}>
          <CanvasMotion>
            <m.div
              data-testid="sheet-scrim"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, transition: { duration: duration.fast, ease: easing.accelerate } }}
              transition={{ duration: duration.base, ease: easing.decelerate }}
              className="absolute inset-0 cursor-default bg-ink/25 backdrop-blur-sm"
              onClick={onClose}
            />
            <m.div
              ref={panelRef}
              /* div 需要 tabIndex 才能接收打开时的程序化焦点。 */
              tabIndex={-1}
              role="dialog"
              aria-modal="true"
              aria-label="行程详情"
              data-testid={testId}
              data-detent={detent}
              initial={{ y: closedY }}
              animate={{ y: yFor(detent) }}
              exit={{ y: closedY, transition: { duration: duration.base, ease: easing.accelerate } }}
              transition={
                entered
                  ? { y: spring }
                  : { y: { duration: duration.slow, ease: easing.decelerate } }
              }
              onAnimationComplete={() => setEntered(true)}
              drag="y"
              dragListener={false}
              dragControls={dragControls}
              dragConstraints={{ top: 0, bottom: closedY }}
              dragElastic={{ top: 0.04, bottom: 0 }}
              dragMomentum={false}
              onDragStart={() => {
                draggedRef.current = true;
              }}
              onDragEnd={handleDragEnd}
              style={{ y, height: panelHeight, zIndex: 10 }}
              className={cn(
                'absolute inset-x-0 bottom-0 flex flex-col overflow-hidden border-t border-stroke bg-panel shadow-lg',
                'rounded-t-card pb-[env(safe-area-inset-bottom)]'
              )}
            >
              <button
                type="button"
                aria-label={detent === 55 ? '展开行程详情' : '收起行程详情'}
                aria-expanded={detent === 92}
                data-testid="sheet-handle"
                onPointerDown={(event) => {
                  draggedRef.current = false;
                  dragControls.start(event);
                }}
                onClick={() => {
                  if (draggedRef.current) {
                    draggedRef.current = false;
                    return;
                  }
                  snapTo(detent === 55 ? 92 : 55);
                }}
                className="flex h-11 flex-none cursor-grab touch-none items-center justify-center active:cursor-grabbing"
              >
                <span className="h-1 w-9 rounded-full bg-ink/15" />
              </button>
              <div className="min-h-0 flex-1">{children}</div>
            </m.div>
          </CanvasMotion>
        </div>
      )}
    </AnimatePresence>
  );
};
