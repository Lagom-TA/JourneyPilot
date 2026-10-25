import React from 'react';
import { ChevronDown, Check } from 'lucide-react';
import { cn } from '../../lib/utils';
import { Popover } from './Popover';

/* 菜单仅支持点击选择，尚未实现方向键导航。 */
export interface SelectOption {
  value: string;
  label: string;
  description?: string;
}

export interface SelectMenuProps {
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  testId?: string;
  className?: string;
}

export const SelectMenu: React.FC<SelectMenuProps> = ({
  value,
  options,
  onChange,
  placeholder = '请选择',
  disabled,
  testId,
  className,
}) => {
  const selected = options.find((o) => o.value === value);

  return (
    <Popover
      placement="bottom-start"
      offset={6}
      matchTriggerWidth
      className="rounded-card overflow-hidden py-1"
      trigger={({ ref, open, toggle }) => (
        <button
          ref={ref}
          type="button"
          data-testid={testId}
          data-state={open ? 'open' : 'closed'}
          disabled={disabled}
          onClick={toggle}
          className={cn(
            'flex w-full items-center justify-between gap-2 rounded-card border border-stroke',
            'bg-surface px-3 text-sm text-ink',
            'transition-[border-color,background-color] duration-base ease-standard',
            'hover:border-stroke disabled:opacity-50 disabled:pointer-events-none',
            open && 'border-accent',
            className
          )}
        >
          <span className={cn('truncate', selected ? 'text-ink' : 'text-ink-secondary')}>
            {selected ? selected.label : placeholder}
          </span>
          <ChevronDown
            size={15}
            className={cn(
              'flex-shrink-0 text-ink-secondary transition-transform duration-fast ease-standard',
              open && 'rotate-180'
            )}
          />
        </button>
      )}
    >
      {(close) => (
        <div data-testid={testId ? `${testId}-menu` : undefined} className="max-h-64 overflow-y-auto overscroll-contain">
          {options.map((opt) => {
            const isSelected = opt.value === value;
            return (
              <button
                key={opt.value}
                type="button"
                data-testid={testId ? `${testId}-option-${opt.value}` : undefined}
                onClick={() => {
                  onChange(opt.value);
                  close();
                }}
                className={cn(
                  'flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm',
                  'transition-colors duration-fast ease-standard',
                  isSelected
                    ? 'bg-accent-soft text-accent'
                    : 'text-ink hover:bg-ink/[0.03]'
                )}
              >
                <span className="min-w-0 flex-1">
                  <span className={cn('block truncate font-medium', isSelected && 'text-accent')}>
                    {opt.label}
                  </span>
                  {opt.description && (
                    <span className="block truncate text-[11px] text-ink-secondary">
                      {opt.description}
                    </span>
                  )}
                </span>
                {isSelected && <Check size={14} className="flex-shrink-0 text-accent" />}
              </button>
            );
          })}
        </div>
      )}
    </Popover>
  );
};
