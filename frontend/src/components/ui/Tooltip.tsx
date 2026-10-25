import React, { useState, useRef } from 'react';
import { cn } from '../../lib/utils';

/* 提示内容可能是补充说明，不能代替控件自身的可及名。 */
interface TooltipProps {
  content: string;
  children: React.ReactNode;
  position?: 'top' | 'bottom' | 'left' | 'right';
  delay?: number;
  disabled?: boolean;
  /* 满宽触发器也需要给包裹层传入满宽样式。 */
  className?: string;
}

export const Tooltip: React.FC<TooltipProps> = ({
  content,
  children,
  position = 'top',
  delay = 300,
  disabled = false,
  className,
}) => {
  const [visible, setVisible] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  const show = () => {
    if (disabled) return;
    timerRef.current = setTimeout(() => setVisible(true), delay);
  };
  const hide = () => {
    clearTimeout(timerRef.current);
    setVisible(false);
  };

  const positionClasses = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-2',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
    left: 'right-full top-1/2 -translate-y-1/2 mr-2',
    right: 'left-full top-1/2 -translate-y-1/2 ml-2',
  };

  return (
    <div
      className={cn('relative inline-flex', className)}
      onMouseEnter={show}
      onMouseLeave={hide}
    >
      {children}
      {visible && !disabled && (
        <div
          className={cn(
            'absolute z-50 px-2.5 py-1.5 text-xs font-medium',
            'bg-ink text-white rounded-card shadow-lg',
            'whitespace-nowrap pointer-events-none',
            'animate-fade-in [animation-duration:var(--dur-fast)]',
            positionClasses[position]
          )}
        >
          {content}
        </div>
      )}
    </div>
  );
};
