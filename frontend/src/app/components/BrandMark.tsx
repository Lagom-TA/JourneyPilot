import { cn } from "../../lib/utils";
import React from 'react';
import brandIcon from '../../assets/brand/brand-icon-ink.webp';
import brandWord from '../../assets/brand/brand-word-ink.webp';
export const BrandMark: React.FC<{
    size?: number;
    className?: string;
}> = ({ size = 24, className }) => (<img data-brand-mark src={brandIcon} alt="" aria-hidden height={size} style={{ height: size, width: 'auto' }} className={cn('block select-none', className)} decoding="async"/>);
export const BrandWordmark: React.FC<{
    height?: number;
    className?: string;
}> = ({ height = 13, className }) => (<img data-brand-wordmark src={brandWord} alt="JourneyPilot" height={height} style={{ height, width: 'auto' }} className={cn('block select-none', className)} decoding="async"/>);
