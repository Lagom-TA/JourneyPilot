import { ArrowUpRight } from "lucide-react";
import { type DaySummaryVM } from "../../model/itineraryPresentation";
import { cn } from "../../../../lib/utils";
import React from 'react';
interface DaySummaryCardProps {
    day: DaySummaryVM;
    onOpen: () => void;
    cardRef?: React.Ref<HTMLButtonElement>;
    compact?: boolean;
    active?: boolean;
    unscheduled?: boolean;
}
function placeClue(day: DaySummaryVM): string | null {
    const titles = day.nodes
        .filter((node) => node.entityKind !== 'transport' && node.role === 'place')
        .map((node) => node.title)
        .slice(0, 2);
    return titles.length > 0 ? titles.join(' → ') : null;
}
export const DaySummaryCard: React.FC<DaySummaryCardProps> = ({ day, onOpen, cardRef, compact = false, active = false, unscheduled = false }) => {
    const metadata = [day.dateLabel, day.weekdayLabel, day.destinationLabel].filter((value): value is string => Boolean(value));
    const accessibleLabel = [`查看第 ${day.day} 天`, metadata.join(' · '), day.theme].filter(Boolean).join('：');
    const clue = placeClue(day);
    return (<button ref={cardRef} type="button" data-testid={`day-summary-card-${day.dayId}`} aria-label={accessibleLabel} aria-pressed={active} onClick={onOpen} className={cn('day-summary-card group', compact && 'is-compact', active && 'is-active')}>
      <span className="day-summary-ordinal" aria-hidden>{String(day.day).padStart(2, '0')}</span>
      <span className="day-summary-copy">
        {metadata.length > 0 && <span className="day-summary-meta">{metadata.join(' · ')}{unscheduled && <span className="day-summary-gap">尚未安排</span>}</span>}
        <span className="day-summary-theme">{day.theme}</span>
        {clue && <span className="day-summary-clue">{clue}</span>}
      </span>
      <ArrowUpRight size={18} aria-hidden className="day-summary-arrow"/>
    </button>);
};
