import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AnimatePresence, m } from 'motion/react';
import { Loader2 } from 'lucide-react';
import { cn } from '../../lib/utils';
import { duration, easing, transitions } from '../../lib/motion';

/* 显式宽度变体可在 domAnimation 下运行，无需加载 domMax。 */
export interface ConfirmActionProps {
  children: React.ReactNode;
  onConfirm: () => void;
  confirmLabel?: string;
  cancelLabel?: string;
  revertAfterMs?: number;
  disabled?: boolean;
  /* 异步确认期间暂停自动收起，由 confirmPending 决定何时结束。 */
  confirmPending?: boolean;
  testId?: string;
  tone?: 'error' | 'accent';
  className?: string;
  triggerClassName?: string;
  triggerLabel?: string;
}

// 悬停底色由外壳统一绘制，避免内层叠色。
const toneClasses = {
  error: {
    shell: 'border-error/20 bg-error/10 text-error hover:bg-error/[0.18]',
    trigger: 'text-error',
    control: 'text-error hover:bg-error/10 hover:text-error',
  },
  accent: {
    shell: 'border-accent/20 bg-accent/10 text-accent hover:bg-accent/[0.18]',
    trigger: 'text-accent',
    control: 'text-accent hover:bg-accent/10 hover:text-accent',
  },
} as const;

export const ConfirmAction: React.FC<ConfirmActionProps> = ({
  children,
  onConfirm,
  confirmLabel = '确认',
  cancelLabel = '取消',
  revertAfterMs = 4000,
  disabled,
  confirmPending = false,
  testId,
  tone = 'error',
  className,
  triggerClassName,
  triggerLabel,
}) => {
  const [armed, setArmed] = useState(false);
  // 用状态触发下一次渲染，待 confirmPending 更新后再决定是否收起。
  const [fired, setFired] = useState(false);
  const timerRef = useRef<number | null>(null);
  const t = toneClasses[tone];

  const clearTimer = useCallback(() => {
    if (timerRef.current != null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const disarm = useCallback(() => {
    if (confirmPending) return;
    clearTimer();
    setFired(false);
    setArmed(false);
  }, [clearTimer, confirmPending]);

  const arm = useCallback(() => {
    setFired(false);
    setArmed(true);
    clearTimer();
    timerRef.current = window.setTimeout(() => setArmed(false), revertAfterMs);
  }, [clearTimer, revertAfterMs]);

  const confirm = useCallback(() => {
    clearTimer();
    setFired(true);
    onConfirm();
  }, [clearTimer, onConfirm]);

  useEffect(() => {
    if (confirmPending) {
      clearTimer();
      return;
    }
    if (fired) {
      setFired(false);
      setArmed(false);
    }
  }, [confirmPending, fired, clearTimer]);

  useEffect(() => clearTimer, [clearTimer]);

  return (
    <div
      data-confirm-action=""
      className={cn(
        'inline-flex items-center gap-1 rounded-card border px-2 py-1 transition-colors duration-base ease-standard',
        t.shell,
        className
      )}
    >
      <button
        type="button"
        data-testid={testId}
        aria-label={triggerLabel}
        disabled={disabled || confirmPending}
        onClick={() => (armed ? disarm() : arm())}
        className={cn(
          'inline-flex h-7 items-center gap-1.5 rounded-card px-2.5 text-xs font-medium',
          'transition-colors duration-base ease-standard',
          'disabled:pointer-events-none disabled:opacity-50',
          armed && 'hidden',
          t.trigger,
          triggerClassName
        )}
      >
        {children}
      </button>
      <AnimatePresence initial={false}>
        {armed && (
          <m.div
            key="confirm-pair"
            initial={{ opacity: 0, width: 0 }}
            animate={{
              opacity: 1,
              width: 'auto',
              transition: {
                width: transitions.enter(duration.base),
                opacity: { duration: duration.fast, ease: easing.decelerate },
              },
            }}
            /* 退出单独指定 transition，避免继承入场的减速曲线。 */
            exit={{
              opacity: 0,
              width: 0,
              transition: {
                width: transitions.exit(duration.fast),
                opacity: { duration: duration.fast, ease: easing.accelerate },
              },
            }}
            className="flex items-center gap-1 overflow-hidden"
          >
            <button
              type="button"
              data-testid={testId ? `${testId}-confirm` : undefined}
              onClick={confirm}
              disabled={confirmPending}
              className={cn(
                'inline-flex h-7 items-center gap-1.5 whitespace-nowrap rounded-card px-2.5 text-xs font-semibold',
                'transition-colors duration-fast ease-standard',
                'disabled:pointer-events-none',
                t.control
              )}
            >
              {confirmPending && <Loader2 size={12} className="animate-spin" />}
              {confirmLabel}
            </button>
            {!confirmPending && (
              <button
                type="button"
                data-testid={testId ? `${testId}-dismiss` : undefined}
                onClick={disarm}
                className={cn(
                  'inline-flex h-7 items-center whitespace-nowrap rounded-card px-2.5 text-xs font-medium text-ink-secondary',
                  'transition-colors duration-fast ease-standard hover:bg-ink/5 hover:text-ink'
                )}
              >
                {cancelLabel}
              </button>
            )}
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
};
