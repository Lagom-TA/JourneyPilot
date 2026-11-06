import React from 'react';
import { AnimatePresence, animate, useDragControls, useMotionValue } from 'motion/react';
import type { PanInfo } from 'motion/react';
import { X } from 'lucide-react';
import { PresenceSection } from '../../../../components/ui/PresenceSurface';
import { duration, easing, spring } from '../../../../lib/motion';
import { releaseSheet, sheetOffset, type SheetDetent } from '../../../../lib/sheetDetents';
import { useOverlayDismiss } from '../../../../hooks/useOverlayDismiss';

export function DeliveryMobileSheet({ open, onClose, children }: { open: boolean; onClose: () => void; children: React.ReactNode }) {
  const [detent, setDetent] = React.useState<SheetDetent>(55);
  const [panelHeight, setPanelHeight] = React.useState(() => window.innerHeight * .92);
  const [entered, setEntered] = React.useState(false);
  const panelRef = React.useRef<HTMLElement>(null);
  const y = useMotionValue(panelHeight);
  const dragControls = useDragControls();
  const dragged = React.useRef(false);
  const handleRef = React.useRef<HTMLButtonElement>(null);
  useOverlayDismiss({ open, onDismiss: onClose });
  React.useLayoutEffect(() => {
    const panel = panelRef.current;
    if (!open || !panel) return;
    const update = () => setPanelHeight(panel.offsetHeight);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(panel);
    return () => observer.disconnect();
  }, [open]);
  React.useEffect(() => {
    if (!open) return;
    setDetent(55);
    setEntered(false);
    const frame = window.requestAnimationFrame(() => handleRef.current?.focus({ preventScroll: true }));
    return () => window.cancelAnimationFrame(frame);
  }, [open]);
  const snapTo = React.useCallback((target: SheetDetent) => {
    if (target === detent) void animate(y, sheetOffset(panelHeight, target), spring);
    else setDetent(target);
  }, [detent, panelHeight, y]);
  const release = (_event: MouseEvent | TouchEvent | PointerEvent, info: PanInfo) => {
    const target = releaseSheet(panelHeight, y.get(), info.velocity.y, detent);
    if (target === 0) onClose();
    else snapTo(target);
  };
  return (
    <AnimatePresence>
      {open && (
        <PresenceSection
          ref={panelRef}
          className="journey-mobile-sheet"
          aria-label="旅行日程"
          data-testid="canvas-sheet"
          data-detent={detent}
          initial={{ y: panelHeight }}
          animate={{ y: sheetOffset(panelHeight, detent) }}
          exit={{ y: panelHeight, transition: { duration: duration.base, ease: easing.accelerate } }}
          transition={entered ? spring : { duration: duration.slow, ease: easing.decelerate }}
          onAnimationComplete={() => setEntered(true)}
          style={{ y }}
          drag="y"
          dragListener={false}
          dragControls={dragControls}
          dragConstraints={{ top: 0, bottom: panelHeight }}
          dragElastic={{ top: 0.04, bottom: 0 }}
          dragMomentum={false}
          onDragStart={() => { dragged.current = true; }}
          onDragEnd={release}
        >
          <div className="journey-mobile-sheet-controls">
            <button
              ref={handleRef}
              type="button"
              data-testid="sheet-handle"
              aria-label={detent === 92 ? '收起旅行日程' : '展开旅行日程'}
              aria-expanded={detent === 92}
              onPointerDown={(event) => { dragged.current = false; dragControls.start(event); }}
              onClick={() => { if (dragged.current) { dragged.current = false; return; } snapTo(detent === 55 ? 92 : 55); }}
            ><span /></button>
            <button type="button" aria-label="收起日程，查看地图" onClick={onClose}><X size={17} /></button>
          </div>
          <div className="journey-mobile-panels">{children}</div>
        </PresenceSection>
      )}
    </AnimatePresence>
  );
}
