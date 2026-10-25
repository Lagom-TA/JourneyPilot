import { cn } from "../../lib/utils";
import React from 'react';
import blankTabs from '../../assets/marks/blank-tabs.png';
import emptySleeve from '../../assets/marks/empty-sleeve.png';
const MARK_SRC = {
    'empty-sleeve': emptySleeve,
    'blank-tabs': blankTabs,
} as const;
export type ChartMarkName = keyof typeof MARK_SRC;
interface ChartMarkProps {
    mark: ChartMarkName;
    size?: number;
    className?: string;
}
export const ChartMark: React.FC<ChartMarkProps> = ({ mark, size = 104, className }) => {
    const src = MARK_SRC[mark];
    return (<span aria-hidden data-chart-mark={mark} style={{
            width: size,
            height: size,
            maskImage: `url(${src})`,
            WebkitMaskImage: `url(${src})`,
            maskSize: 'contain',
            WebkitMaskSize: 'contain',
            maskRepeat: 'no-repeat',
            WebkitMaskRepeat: 'no-repeat',
            maskPosition: 'center',
            WebkitMaskPosition: 'center',
        }} className={cn('block shrink-0 bg-ink-secondary/25', className)}/>);
};
