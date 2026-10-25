import React from 'react';
import { cn } from '../../lib/utils';

/* 淡底对比度有限，选中态同时保留描边与字重。 */
export const Chip: React.FC<{
  selected?: boolean;
  onClick: () => void;
  label?: string;
  disabled?: boolean;
  children: React.ReactNode;
  className?: string;
}> = ({ selected = false, onClick, label, disabled, children, className }) => (
  <button
    type="button"
    onClick={onClick}
    disabled={disabled}
    aria-pressed={selected}
    aria-label={label}
    className={cn(
      'inline-flex min-h-9 items-center rounded-label border px-3 text-[13px]',
      'transition-colors duration-fast ease-standard',
      'disabled:pointer-events-none disabled:opacity-50',
      selected
        ? 'border-accent bg-accent/10 font-semibold text-accent'
        : 'border-stroke font-medium text-ink-secondary hover:border-ink-muted hover:text-ink',
      className
    )}
  >
    {children}
  </button>
);
