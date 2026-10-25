import type { CSSProperties } from 'react';
import { cn } from '../../lib/utils';

/* 绝对定位覆盖层要求父容器提供定位参照。 */
export function Neatline({
  inset,
  enter = false,
  className,
}: {
  inset?: string;
  enter?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn('neatline', enter && 'neatline-enter', className)}
      style={inset ? ({ '--neatline-inset': inset } as CSSProperties) : undefined}
      aria-hidden
    >
      <span className="neatline-tick neatline-tick-tl" />
      <span className="neatline-tick neatline-tick-tr" />
      <span className="neatline-tick neatline-tick-bl" />
      <span className="neatline-tick neatline-tick-br" />
    </div>
  );
}
