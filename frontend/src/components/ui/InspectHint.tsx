import React from 'react';
import { Info } from 'lucide-react';
import { cn } from '../../lib/utils';
import { Popover, type PopoverPlacement } from './Popover';
import { Tooltip } from './Tooltip';

export interface InspectHintProps {
  children: React.ReactNode;
  label?: string;
  placement?: PopoverPlacement;
  panelClassName?: string;
  className?: string;
  testId?: string;
  size?: 'sm' | 'md';
}

export const InspectHint: React.FC<InspectHintProps> = ({
  children,
  label = '运行检查',
  placement = 'bottom-end',
  panelClassName,
  className,
  testId = 'inspect-hint',
  size = 'md',
}) => {
  if (children == null || children === false) return null;

  const dim = size === 'sm' ? 'h-5 w-5' : 'h-6 w-6';
  const icon = size === 'sm' ? 11 : 13;

  return (
    <Popover
      placement={placement}
      className={cn('max-w-[min(360px,calc(100vw-24px))]', panelClassName)}
      trigger={({ ref, open, toggle }) => (
        <Tooltip content={label} position="left" disabled={open}>
          <button
            ref={ref}
            type="button"
            data-testid={testId}
            aria-label={label}
            aria-expanded={open}
            onClick={(e) => {
              e.stopPropagation();
              toggle();
            }}
            className={cn(
              'inline-flex shrink-0 items-center justify-center rounded-card border border-stroke bg-surface text-ink-muted transition-[color,border-color,background-color] duration-fast ease-standard',
              'hover:border-accent/35 hover:bg-accent-soft hover:text-accent',
              open && 'border-accent/40 bg-accent-soft text-accent',
              dim,
              className
            )}
          >
            <Info size={icon} strokeWidth={2.25} />
          </button>
        </Tooltip>
      )}
    >
      <div data-testid={`${testId}-panel`} className="p-3 text-left">
        {children}
      </div>
    </Popover>
  );
};

export const InspectSectionTitle: React.FC<{ children: React.ReactNode; className?: string }> = ({
  children,
  className,
}) => (
  <p className={cn('text-[11px] font-semibold tracking-wide text-ink-secondary', className)}>{children}</p>
);

export const InspectRow: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div className="flex items-start justify-between gap-3 text-[11px] leading-relaxed">
    <span className="shrink-0 text-ink-muted">{label}</span>
    <span className="min-w-0 break-words text-right font-mono text-ink-secondary">{value}</span>
  </div>
);
