
import type { Transition, Variants } from 'motion/react';

// 动效库使用秒；毫秒值由 durationMs 提供。
export const duration = {
  fast: 0.12,
  base: 0.2,
  slow: 0.32,
  emphasis: 0.48,
  numberRoll: 0.45,
  loop: 1.2,
  loopDrift: 2.4,
} as const;

export const durationMs = {
  fast: 120,
  base: 200,
  slow: 320,
  emphasis: 480,
  numberRoll: 450,
  loop: 1200,
  loopDrift: 2400,
} as const;

// 此阈值触发停滞状态，不是动画时长。
export const stallThresholdMs = 12_000;

export const easing = {
  standard: [0.2, 0, 0.38, 0.9],
  decelerate: [0, 0, 0.38, 0.9],
  accelerate: [0.2, 0, 1, 0.9],
} as const;

// 弹簧只用于空间移动，不能让透明度与颜色过冲。
export const spring: Transition = {
  type: 'spring',
  stiffness: 300,
  damping: 24,
};

export const stagger = {
  step: 0.04,
  maxTotal: 0.48,
} as const;

// 项数增加时缩短间隔，保持编排总时长不超过上限。
export function staggerStep(count: number): number {
  if (count <= 1) return 0;
  return Math.min(stagger.step, stagger.maxTotal / count);
}

export const transitions = {
  standard: (d: number = duration.base): Transition => ({ duration: d, ease: easing.standard }),
  enter: (d: number = duration.slow): Transition => ({ duration: d, ease: easing.decelerate }),
  exit: (d: number = duration.base): Transition => ({ duration: d, ease: easing.accelerate }),
  spatial: spring,
  numberRoll: (): Transition => ({ duration: duration.numberRoll, ease: easing.decelerate }),
} as const;


export const fadeIn: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: transitions.enter() },
  exit: { opacity: 0, transition: transitions.exit(duration.fast) },
};

export const slideUp: Variants = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0, transition: transitions.enter() },
  exit: { opacity: 0, y: -4, transition: transitions.exit(duration.fast) },
};

export const emphasisEnter: Variants = {
  hidden: { opacity: 0, y: 14, scale: 0.985 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: {
      opacity: transitions.enter(duration.slow),
      y: { ...spring, duration: duration.emphasis },
      scale: { ...spring, duration: duration.emphasis },
    },
  },
  exit: {
    opacity: 0,
    y: -6,
    scale: 0.995,
    transition: transitions.exit(duration.fast),
  },
};

export const staggerItem: Variants = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0, transition: transitions.enter(duration.base) },
  exit: { opacity: 0, y: -4, transition: transitions.exit(duration.fast) },
};

export function staggerContainer(count = 0): Variants {
  return {
    hidden: {},
    visible: {
      transition: { staggerChildren: count > 0 ? staggerStep(count) : stagger.step },
    },
  };
}

export const attentionPulse = {
  backgroundColor: [
    'var(--color-accent-soft)',
    'color-mix(in srgb, var(--color-accent) 16%, transparent)',
    'var(--color-accent-soft)',
    'color-mix(in srgb, var(--color-accent) 16%, transparent)',
    'var(--color-accent-soft)',
  ] as string[],
  transition: { duration: duration.emphasis, ease: easing.standard },
};
