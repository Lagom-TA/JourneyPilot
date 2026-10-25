import React from 'react';
import { m } from 'motion/react';
import { cn } from '../../lib/utils';
import { staggerContainer, staggerItem } from '../../lib/motion';


export const RuledList: React.FC<{
  count: number;
  topRule?: boolean;
  className?: string;
  children: React.ReactNode;
}> = ({ count, topRule = false, className, children }) => (
  <m.div
    variants={staggerContainer(count)}
    initial="hidden"
    animate="visible"
    className={cn('divide-y divide-stroke/60 border-b border-stroke/60', topRule && 'border-t border-stroke/60', className)}
  >
    {children}
  </m.div>
);

export const RuledRow: React.FC<{
  title: React.ReactNode;
  meta?: React.ReactNode;
  trailing?: React.ReactNode;
  onClick?: () => void;
  active?: boolean;
  testId?: string;
  className?: string;
  label?: string;
}> = ({ title, meta, trailing, onClick, active, testId, className, label }) => {
  const body = (
    <>
      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <span
          className={cn(
            'min-w-0 break-words text-[15px] font-semibold leading-snug',
            active ? 'text-accent' : 'text-ink'
          )}
        >
          {title}
        </span>
        {meta && (
          <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-secondary">
            {meta}
          </span>
        )}
      </span>
      {trailing && (
        <span className="flex flex-shrink-0 items-center gap-2 self-start pt-0.5">{trailing}</span>
      )}
    </>
  );

  const shape = cn(
    'flex w-full items-start gap-4 px-2 py-4 text-left',
    'transition-colors duration-fast ease-standard',
    active && 'bg-accent/8',
    className
  );

  const litGround = 'hover:bg-highlight';

  if (!onClick) {
    return (
      <m.div variants={staggerItem} data-testid={testId} className={shape}>
        {body}
      </m.div>
    );
  }

  return (
    <m.div variants={staggerItem}>
      <button
        type="button"
        data-testid={testId}
        aria-label={label}
        onClick={onClick}
        className={cn(shape, !active && litGround)}
      >
        {body}
      </button>
    </m.div>
  );
};

// 混合中文读数不加拉丁标签字距，避免量词间距被拉宽。
export const RuledReadout: React.FC<{ children: React.ReactNode; className?: string }> = ({
  children,
  className,
}) => (
  <span className={cn('text-[11px] tabular-nums text-ink-muted', className)}>{children}</span>
);
