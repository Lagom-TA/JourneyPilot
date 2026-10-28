
import type { Transition, Variants } from 'motion/react';

// 动效库使用秒。
export const duration = {
  fast: 0.16,
  base: 0.18,
  slow: 0.25,
  page: 0.22,
  detail: 0.3,
  emphasis: 0.4,
  numberRoll: 0.4,
  loop: 1.2,
  loopDrift: 2.4,
} as const;

export const easing = {
  standard: [0.2, 0, 0.38, 0.9],
  decelerate: [0.16, 1, 0.3, 1],
  accelerate: [0.7, 0, 0.84, 0],
} as const;

// 弹簧只用于空间移动，不能让透明度与颜色过冲。
export const spring: Transition = {
  type: 'spring',
  stiffness: 260,
  damping: 30,
};

export const stagger = {
  step: 0.036,
  maxTotal: 0.4,
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
