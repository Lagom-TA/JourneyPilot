import { m, useIsPresent } from 'motion/react';
import type { HTMLMotionProps } from 'motion/react';
import React from 'react';

export const PresenceFrame = React.forwardRef<HTMLDivElement, HTMLMotionProps<'div'>>(
  function PresenceFrame({ children, ...props }, forwardedRef) {
    const isPresent = useIsPresent();
    const nodeRef = React.useRef<HTMLDivElement | null>(null);
    const forwardedRefRef = React.useRef(forwardedRef);
    forwardedRefRef.current = forwardedRef;
    const setRef = React.useCallback((node: HTMLDivElement | null) => {
      nodeRef.current = node;
      const ref = forwardedRefRef.current;
      if (typeof ref === 'function') ref(node);
      else if (ref) ref.current = node;
    }, []);
    React.useLayoutEffect(() => {
      nodeRef.current?.toggleAttribute('inert', !isPresent);
    }, [isPresent]);

    return (
      <m.div
        {...props}
        ref={setRef}
        aria-hidden={!isPresent || undefined}
      >
        {children}
      </m.div>
    );
  },
);

export function PresenceSection({ children, ...props }: HTMLMotionProps<'section'>) {
  const isPresent = useIsPresent();
  const nodeRef = React.useRef<HTMLElement | null>(null);
  const setRef = React.useCallback((node: HTMLElement | null) => {
    nodeRef.current = node;
  }, []);
  React.useLayoutEffect(() => {
    nodeRef.current?.toggleAttribute('inert', !isPresent);
  }, [isPresent]);

  return (
    <m.section
      {...props}
      ref={setRef}
      aria-hidden={!isPresent || undefined}
    >
      {children}
    </m.section>
  );
}
