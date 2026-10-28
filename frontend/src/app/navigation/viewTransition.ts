import type { Variants } from 'motion/react';
import { duration, easing, transitions } from '../../lib/motion';
import type { ActiveView } from '../state/state';

export type ViewTransitionKind = 'same' | 'peer' | 'detail' | 'reset';

export interface ViewTransition {
  kind: ViewTransitionKind;
  direction: -1 | 0 | 1;
}

const VIEW_ORDER: ActiveView[] = [
  'chat',
  'trips',
  'user-preferences',
  'presets',
  'knowledge-base',
];

export function resolveViewTransition(
  previous: ActiveView,
  next: ActiveView,
  conversationReset: boolean,
): ViewTransition {
  if (previous === next) return { kind: 'same', direction: 0 };
  if (conversationReset) return { kind: 'reset', direction: 0 };
  if ((previous === 'trips' && next === 'chat') || (previous === 'chat' && next === 'trips')) {
    return { kind: 'detail', direction: next === 'chat' ? 1 : -1 };
  }
  return {
    kind: 'peer',
    direction: VIEW_ORDER.indexOf(next) >= VIEW_ORDER.indexOf(previous) ? 1 : -1,
  };
}

function enterDuration(kind: ViewTransitionKind): number {
  if (kind === 'detail') return duration.detail;
  if (kind === 'reset') return duration.slow;
  return duration.page;
}

export const viewTransitionVariants: Variants = {
  enter: ({ kind, direction }: ViewTransition) => ({
    x: direction * (kind === 'detail' ? 32 : 24),
    y: kind === 'reset' ? 12 : 0,
    scale: kind === 'detail' ? 0.985 : 0.995,
  }),
  center: ({ kind }: ViewTransition) => ({
    opacity: 1,
    x: 0,
    y: 0,
    scale: 1,
    transition: {
      duration: enterDuration(kind),
      ease: kind === 'detail' ? easing.standard : easing.decelerate,
    },
  }),
  exit: ({ kind, direction }: ViewTransition) => ({
    opacity: 0,
    x: direction * -(kind === 'detail' ? 20 : 16),
    y: kind === 'reset' ? -8 : 0,
    scale: kind === 'detail' ? 0.99 : 0.995,
    transition: transitions.exit(kind === 'detail' ? duration.base : duration.fast),
  }),
};
