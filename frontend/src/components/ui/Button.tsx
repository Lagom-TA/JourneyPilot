import React from 'react';
import { cn } from '../../lib/utils';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'icon';
type ButtonSize = 'sm' | 'md' | 'lg';

interface ButtonBaseProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  size?: ButtonSize;
  loading?: boolean;
  children: React.ReactNode;
}

/* 图标按钮没有可见文字，必须由自身提供可及名。 */
type ButtonProps =
  | (ButtonBaseProps & { variant?: Exclude<ButtonVariant, 'icon'> })
  | (ButtonBaseProps & { variant: 'icon'; 'aria-label': string });

const variantClasses: Record<ButtonVariant, string> = {
  primary:
    'bg-accent text-on-accent hover:bg-accent-hover active:bg-accent-hover shadow-sm',
  secondary:
    'bg-surface text-ink hover:bg-accent-soft active:bg-accent-soft',
  ghost:
    'bg-transparent text-ink-secondary hover:bg-ink/5 hover:text-ink',
  icon:
    'bg-transparent text-ink-secondary hover:bg-ink/10 hover:text-ink flex items-center justify-center',
};

const sizeClasses: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-xs rounded-card gap-1.5',
  md: 'h-10 px-4 text-sm rounded-card gap-2',
  lg: 'h-12 px-6 text-base rounded-card gap-2',
};

const iconSizeClasses: Record<ButtonSize, string> = {
  sm: 'h-7 w-7 rounded-card',
  md: 'h-9 w-9 rounded-card',
  lg: 'h-11 w-11 rounded-card',
};

export const Button: React.FC<ButtonProps> = ({
  variant = 'primary',
  size = 'md',
  loading = false,
  disabled,
  className,
  children,
  ...props
}) => {
  const isIcon = variant === 'icon';

  return (
    <button
      className={cn(
        'inline-flex items-center justify-center font-medium',
        'transition-[transform,opacity,background-color,color,border-color] duration-fast ease-standard',
        'active:scale-[0.98]',
        'cursor-pointer select-none border-none',
        'disabled:opacity-50 disabled:pointer-events-none disabled:active:scale-100',
        variantClasses[variant],
        isIcon ? iconSizeClasses[size] : sizeClasses[size],
        className
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading && (
        <span className="h-4 w-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
      )}
      {children}
    </button>
  );
};
