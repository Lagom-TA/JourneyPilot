import React from 'react';
import { cn } from '../../lib/utils';

type SkeletonRadius = 'label' | 'card' | 'full' | 'none';
type SkeletonTone = 'surface' | 'panel';

export interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  radius?: SkeletonRadius;
  tone?: SkeletonTone;
}

const radiusClass: Record<SkeletonRadius, string> = {
  none: '',
  label: 'rounded-label',
  card: 'rounded-card',
  full: 'rounded-full',
};

const toneClass: Record<SkeletonTone, string> = {
  surface: 'bg-surface',
  panel: 'bg-panel',
};

export const Skeleton: React.FC<SkeletonProps> = ({
  radius = 'card',
  tone = 'surface',
  className,
  ...props
}) => (
  <div
    className={cn('animate-pulse', radiusClass[radius], toneClass[tone], className)}
    {...props}
  />
);
