import { type DaySummaryVM } from "../../model/itineraryPresentation";
import { type PublicStructuredItineraryV2 } from "../../types/itinerary";
import { DaySummaryCard } from "./DaySummaryCard";
import { LabelledFactList, TripFactReadout } from "./TripFactReadout";
import { cn } from "../../../../lib/utils";
import React from 'react';
interface TripOverviewProps {
    itinerary: PublicStructuredItineraryV2;
    summaries: readonly DaySummaryVM[];
    costCoverageStatement: string | null;
    importantNotes: readonly string[];
    onOpenDay: (day: DaySummaryVM) => void;
    registerDayCard: (dayId: string, node: HTMLButtonElement | null) => void;
    showHeader?: boolean;
    compact?: boolean;
    activeDay?: number | null;
}
function dateRangeLabel(summaries: readonly DaySummaryVM[]): string | null {
    const dates = summaries.map((summary) => summary.dateLabel).filter((value): value is string => Boolean(value));
    if (dates.length === 0)
        return null;
    return dates.length === 1 ? dates[0] : `${dates[0]} – ${dates[dates.length - 1]}`;
}
export const TripOverview: React.FC<TripOverviewProps> = ({ itinerary, summaries, costCoverageStatement, importantNotes, onOpenDay, registerDayCard, showHeader = true, compact = false, activeDay = null, }) => {
    const destinations = [...new Set(summaries.map((summary) => summary.destinationLabel).filter((value): value is string => Boolean(value)))];
    const readouts: Array<{
        label: string;
        value: string;
    }> = [
        ...(destinations.length > 0 ? [{ label: '目的地', value: destinations.join(' · ') }] : []),
        ...(dateRangeLabel(summaries) ? [{ label: '行程期间', value: dateRangeLabel(summaries) as string }] : []),
        { label: '天数', value: `${itinerary.duration_days} 天` },
        ...(costCoverageStatement ? [{ label: '费用', value: costCoverageStatement }] : []),
    ];
    const highlights = itinerary.highlights.filter((highlight) => Boolean(highlight.trim()));
    return (<section data-testid="trip-overview" aria-labelledby={showHeader ? 'trip-overview-title' : undefined} aria-label={!showHeader ? '每日行程导航' : undefined} className={cn('mx-auto w-full max-w-3xl py-1 sm:py-2', compact && 'trip-overview-compact')}>
      {showHeader && (<header className="trip-overview-heading border-b border-stroke pb-5 sm:pb-6">
        <p className="mb-3 text-[11px] font-medium tracking-[0.12em] text-chart">你的旅行手册</p>
        <h2 id="trip-overview-title" className="break-words font-display text-[28px] font-semibold leading-snug tracking-tight text-ink">{itinerary.title}</h2>
        <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-4">
          {readouts.map((entry) => <TripFactReadout key={entry.label} {...entry}/>)}
        </dl>
        {highlights.length > 0 && (<div className="mt-5 border-t border-stroke/60 pt-4">
            <LabelledFactList facts={highlights} testId="overview-highlights"/>
          </div>)}
      </header>)}

      <ol className="mt-5 space-y-3 sm:mt-6 sm:space-y-4" aria-label="每日行程摘要">
        {summaries.map((day) => (<li key={day.dayId}>
            <DaySummaryCard day={day} onOpen={() => onOpenDay(day)} cardRef={(node) => registerDayCard(day.dayId, node)} compact={compact} active={activeDay === day.day}/>
          </li>))}
      </ol>


      {importantNotes.length > 0 && (<section className="mt-6 border-t border-stroke pt-5" aria-labelledby="overview-notes-heading" data-testid="overview-important-notes">
          <h3 id="overview-notes-heading" className="text-sm font-semibold text-ink">出发前事项</h3>
          <ul className="mt-2 space-y-1.5 text-sm leading-6 text-ink-secondary">
            {importantNotes.map((note) => <li key={note} className="break-words">{note}</li>)}
          </ul>
        </section>)}
    </section>);
};
