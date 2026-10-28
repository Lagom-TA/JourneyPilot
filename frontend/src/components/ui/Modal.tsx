import React, { useEffect, useRef } from 'react';
import { AnimatePresence, m } from 'motion/react';
import type { Variants } from 'motion/react';
import { cn } from '../../lib/utils';
import { duration, easing, transitions } from '../../lib/motion';
import { X } from 'lucide-react';
import { Button } from './Button';
import { useOverlayDismiss } from '../../hooks/useOverlayDismiss';

const scrimVariants: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: duration.base, ease: easing.decelerate } },
  exit: { opacity: 0, transition: transitions.exit(duration.fast) },
};

const panelVariants: Variants = {
  hidden: { opacity: 0, y: 8, scale: 0.985 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { duration: duration.base, ease: easing.decelerate },
  },
  exit: {
    opacity: 0,
    y: 6,
    scale: 0.99,
    transition: transitions.exit(duration.fast),
  },
};

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  maxWidth?: string;
}

export const Modal: React.FC<ModalProps> = ({
  open,
  onClose,
  title,
  children,
  maxWidth = 'max-w-lg',
}) => {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [open]);

  useOverlayDismiss({ open, onDismiss: onClose, panelRef });

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 flex items-center justify-center p-4" style={{ zIndex: 1200 }}>
          <m.button
            type="button"
            data-testid="modal-scrim"
            /* 遮罩仅响应指针，键盘与读屏通过关闭按钮或 Esc 退出。 */
            aria-hidden="true"
            tabIndex={-1}
            className="absolute inset-0 cursor-default bg-ink/25 backdrop-blur-sm"
            onClick={onClose}
            variants={scrimVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
          />
          <m.div
            ref={panelRef}
            /* div 需要 tabIndex 才能接收打开时的程序化焦点。 */
            tabIndex={-1}
            /* 这里只移动并归还焦点，未实现 Tab 焦点循环。 */
            role="dialog"
            aria-modal="true"
            aria-label={title}
            className={cn(
              'relative w-full rounded-card border border-stroke bg-panel p-6 shadow-lg',
              'max-h-[min(90vh,800px)] overflow-y-auto overscroll-contain',
              maxWidth,
              'mx-auto shadow-lg'
            )}
            variants={panelVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
          >
            {title && (
              <div className="flex items-center justify-between mb-4 gap-2">
                <h3 className="text-base font-semibold text-ink">
                  {title}
                </h3>
                <Button variant="icon" size="sm" aria-label="关闭" onClick={onClose}>
                  <X size={16} />
                </Button>
              </div>
            )}
            {children}
          </m.div>
        </div>
      )}
    </AnimatePresence>
  );
};
