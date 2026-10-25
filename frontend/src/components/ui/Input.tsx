import React from 'react';
import { cn } from '../../lib/utils';


// 焦点底线只改变透明度，不影响字段布局。
export const RULED_FIELD = cn(
  'relative flex min-h-11 w-full items-center gap-2 border-b border-stroke',
  'after:pointer-events-none after:absolute after:inset-x-0 after:-bottom-px after:h-[1.5px]',
  'after:bg-accent after:opacity-0 after:transition-opacity after:duration-fast after:ease-standard',
  'focus-within:after:opacity-100'
);

export const FIELD_LABEL = 'mb-1 block text-[13px] font-medium text-ink-secondary';

export const FIELD_VALUE = 'text-[15px] text-ink placeholder:text-ink-muted';

export const Field: React.FC<{
  label: string;
  invalid?: boolean;
  className?: string;
  children: React.ReactNode;
}> = ({ label, invalid, className, children }) => (
  <div className={cn('min-w-0 flex-1', className)}>
    <label className={FIELD_LABEL}>{label}</label>
    <div className={cn(RULED_FIELD, invalid && 'border-error after:bg-error after:opacity-100')}>
      {children}
    </div>
  </div>
);

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  icon?: React.ReactNode;
  iconClassName?: string;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, icon, iconClassName, ...props },
  ref
) {
  return (
    <div className={RULED_FIELD}>
      {icon && (
        <span
          className={cn(
            'pointer-events-none absolute top-1/2 -translate-y-1/2 text-ink-muted',
            iconClassName || 'left-0'
          )}
        >
          {icon}
        </span>
      )}
      <input
        ref={ref}
        className={cn(
          'min-w-0 flex-1 border-none bg-transparent py-2',
          FIELD_VALUE,
          icon && !iconClassName ? 'pl-7' : '',
          className
        )}
        {...props}
      />
    </div>
  );
});

interface TextAreaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {}

export const TextArea: React.FC<TextAreaProps> = ({ className, ...props }) => {
  return (
    <textarea
      className={cn(
        'w-full resize-none rounded-card border border-stroke bg-surface px-4 py-3',
        'text-[15px] text-ink placeholder:text-ink-muted',
        'transition-colors duration-base ease-standard',
        className
      )}
      {...props}
    />
  );
};
