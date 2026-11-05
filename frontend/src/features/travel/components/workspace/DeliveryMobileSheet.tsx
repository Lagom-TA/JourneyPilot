import React from 'react';
import { AnimatePresence } from 'motion/react';
import { X } from 'lucide-react';
import { PresenceSection } from '../../../../components/ui/PresenceSurface';
import { duration, easing } from '../../../../lib/motion';

export function DeliveryMobileSheet({ open, onClose, children }: { open: boolean; onClose: () => void; children: React.ReactNode }) {
  const [expanded, setExpanded] = React.useState(false);
  const gestureStart = React.useRef<number | null>(null);
  const dragged = React.useRef(false);
  const handleRef = React.useRef<HTMLButtonElement>(null);
  React.useEffect(() => {
    if (!open) return;
    setExpanded(false);
    const frame = window.requestAnimationFrame(() => handleRef.current?.focus({ preventScroll: true }));
    return () => window.cancelAnimationFrame(frame);
  }, [open]);
  return (
    <AnimatePresence>
      {open && (
        <PresenceSection
          className="journey-mobile-sheet"
          aria-label="旅行日程"
          data-testid="canvas-sheet"
          data-detent={expanded ? 92 : 55}
          initial={{ y: '100%' }}
          animate={{ y: expanded ? 0 : `${(1 - 55 / 92) * 100}%` }}
          exit={{ y: '100%' }}
          transition={{ duration: duration.page, ease: easing.decelerate }}
          onKeyDown={(event) => { if (event.key === 'Escape' && !event.defaultPrevented) { event.preventDefault(); onClose(); } }}
        >
          <div className="journey-mobile-sheet-controls">
            <button
              ref={handleRef}
              type="button"
              data-testid="sheet-handle"
              aria-label={expanded ? '收起行程详情' : '展开行程详情'}
              aria-expanded={expanded}
              onPointerDown={(event) => { gestureStart.current = event.clientY; dragged.current = false; event.currentTarget.setPointerCapture(event.pointerId); }}
              onPointerUp={(event) => {
                const delta = event.clientY - (gestureStart.current ?? event.clientY);
                gestureStart.current = null;
                if (Math.abs(delta) < 36) return;
                dragged.current = true;
                if (delta < 0) setExpanded(true);
                else if (expanded) setExpanded(false);
                else onClose();
              }}
              onPointerCancel={() => { gestureStart.current = null; dragged.current = false; }}
              onClick={() => { if (dragged.current) { dragged.current = false; return; } setExpanded((value) => !value); }}
            ><span /></button>
            <button type="button" aria-label="收起日程，查看地图" onClick={onClose}><X size={17} /></button>
          </div>
          <div className="journey-mobile-panels">{children}</div>
        </PresenceSection>
      )}
    </AnimatePresence>
  );
}
