import React, { useCallback, useEffect, useRef, useState } from 'react';
import type { PanInfo } from 'motion/react';
import { AnimatePresence, animate, m, useDragControls, useMotionValue } from 'motion/react';
import { cn } from '../../lib/utils';
import { duration, easing, spring } from '../../lib/motion';
import { CanvasMotion } from './CanvasMotion';
import { useOverlayDismiss } from '../../hooks/useOverlayDismiss';

/* 拖拽需要 domMax，由 CanvasMotion 异步加载。 */

export type SheetDetent = 55 | 92;

interface SheetProps {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  initialDetent?: SheetDetent;
  testId?: string;
}

const PROJECTION_WINDOW_S = 0.2;
const FLICK_VELOCITY = 900;

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
    (detent: SheetDetent) => panelHeight - Math.round(vh * (detent / 100)),
    [panelHeight, vh]
  );
  const closedY = panelHeight;

  const [detent, setDetent] = useState<SheetDetent>(initialDetent);
  const [entered, setEntered] = useState(false);
  const y = useMotionValue(closedY);
  const dragControls = useDragControls();
  // 拖拽结束后的 click 不能再次切换停靠位置。
  const draggedRef = useRef(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useOverlayDismiss({ open, onDismiss: onClose, panelRef });

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
        animate(y, yFor(target), spring);
      } else {
        setDetent(target);
      }
    },
    [detent, y, yFor]
  );

  const handleDragEnd = useCallback(
    (_event: MouseEvent | TouchEvent | PointerEvent, info: PanInfo) => {
      const position = y.get();
      const velocity = info.velocity.y;

      if (velocity > FLICK_VELOCITY) {
        if (detent === 55) {
          onClose();
        } else {
          snapTo(55);
        }
        return;
      }
      if (velocity < -FLICK_VELOCITY) {
        snapTo(92);
        return;
      }

      const projected = position + velocity * PROJECTION_WINDOW_S;
      const anchors: Array<{ y: number; resolve: () => void }> = [
        { y: yFor(92), resolve: () => snapTo(92) },
        { y: yFor(55), resolve: () => snapTo(55) },
        { y: closedY, resolve: onClose },
      ];
      anchors.reduce((best, anchor) =>
        Math.abs(anchor.y - projected) < Math.abs(best.y - projected) ? anchor : best
      ).resolve();
    },
    [closedY, detent, onClose, snapTo, y, yFor]
  );

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50">
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
              style={{ y, height: panelHeight }}
              className={cn(
                'absolute inset-x-0 bottom-0 flex flex-col overflow-hidden border-t border-stroke bg-panel shadow-lg',
                'rounded-t-card pb-[env(safe-area-inset-bottom)]'
              )}
            >
              <div
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
                <div className="h-1 w-9 rounded-full bg-ink/15" />
              </div>
              <div className="min-h-0 flex-1">{children}</div>
            </m.div>
          </CanvasMotion>
        </div>
      )}
    </AnimatePresence>
  );
};
