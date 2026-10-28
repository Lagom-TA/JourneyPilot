import { m, useIsPresent } from 'motion/react';
import type { HTMLMotionProps } from 'motion/react';

export function PresenceFrame({ children, ...props }: HTMLMotionProps<'div'>) {
  const isPresent = useIsPresent();
  return (
    <m.div
      {...props}
      ref={(node) => node?.toggleAttribute('inert', !isPresent)}
      aria-hidden={!isPresent || undefined}
    >
      {children}
    </m.div>
  );
}

export function PresenceSection({ children, ...props }: HTMLMotionProps<'section'>) {
  const isPresent = useIsPresent();
  return (
    <m.section
      {...props}
      ref={(node) => node?.toggleAttribute('inert', !isPresent)}
      aria-hidden={!isPresent || undefined}
    >
      {children}
    </m.section>
  );
}
