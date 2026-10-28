import { ArrowUpRight, CalendarRange, Droplets } from "lucide-react";
import { m } from "motion/react";
import { WEATHER_HISTORICAL_LABEL } from "../../model/deliveryLabels";
import { type DaySummaryVM } from "../../model/itineraryPresentation";
import { isRainy } from "../../model/weatherViewModel";
import { duration, easing } from "../../../../lib/motion";
import { cn } from "../../../../lib/utils";
import { DayOrdinalChip } from "./DayOrdinalChip";
import { TimelineNodeMark } from "./TimelineNodeMark";
import { WeatherIcon } from "./WeatherStrip";
import React from 'react';
interface DaySummaryCardProps {
    day: DaySummaryVM;
    onOpen: () => void;
    cardRef?: React.Ref<HTMLButtonElement>;
    compact?: boolean;
    active?: boolean;
}
function DayWeather({ weather }: {
    weather: NonNullable<DaySummaryVM['weather']>;
}) {
    const seasonal = weather.dataKind === 'seasonal_baseline';
    return (<span data-testid="day-weather-badge" className="inline-flex min-h-7 max-w-full items-center gap-1.5 text-[11px] font-medium text-ink-secondary">
      {seasonal
            ? <CalendarRange size={14} className="shrink-0 text-chart" aria-hidden/>
            : <WeatherIcon kind={weather.icon} size={14} className="shrink-0 text-accent" aria-hidden/>}
      <span className="min-w-0 break-words">
        {seasonal ? '季节参考' : weather.conditionLabel}
        {weather.temperatureLabel ? `${seasonal ? ' · 常见 ' : ' · '}${weather.temperatureLabel}` : ''}
      </span>
      {!seasonal && weather.precipitationProbabilityPct != null && isRainy(weather.icon) && (<span className="inline-flex shrink-0 items-center gap-0.5 tabular-nums text-chart">
          <Droplets size={11} aria-hidden/>
          {weather.precipitationProbabilityPct}%
        </span>)}

      {weather.dataState === 'historical' && (<span data-testid="day-weather-historical" className="shrink-0 text-ink-muted">{WEATHER_HISTORICAL_LABEL}</span>)}
    </span>);
}
export const DaySummaryCard: React.FC<DaySummaryCardProps> = ({ day, onOpen, cardRef, compact = false, active = false }) => {
    const metadata = [day.dateLabel, day.weekdayLabel, day.destinationLabel].filter((value): value is string => Boolean(value));
    const compactMetadata = [day.dateLabel, day.destinationLabel].filter((value): value is string => Boolean(value));
    const accessibleLabel = [`查看第 ${day.day} 天`, ...metadata, day.theme].filter(Boolean).join('：');
    if (compact) {
        return (<button ref={cardRef} type="button" data-testid={`day-summary-card-${day.dayId}`} aria-label={accessibleLabel} aria-pressed={active} onClick={onOpen} className={cn('day-summary-card is-compact group', active && 'is-active')}>
            <span className="flex min-w-0 items-start gap-3">
                <span className="inline-flex shrink-0 items-center">
                    <DayOrdinalChip day={day.day}/>
                </span>
                <span className="min-w-0">
                    <span className="journey-day-nav-meta block text-[11px] text-ink-secondary">{compactMetadata.join(' · ')}</span>
                    <span className="journey-day-nav-theme mt-1 block text-sm font-semibold leading-5 text-ink">{day.theme}</span>
                </span>
            </span>
            <ArrowUpRight size={14} aria-hidden className="mt-1 shrink-0 text-ink-muted transition-colors group-hover:text-accent"/>
        </button>);
    }
    return (<button ref={cardRef} type="button" data-testid={`day-summary-card-${day.dayId}`} aria-label={accessibleLabel} aria-pressed={active} onClick={onOpen} className={cn('day-summary-card group w-full rounded-card border border-stroke bg-panel px-4 py-4 text-left transition-colors duration-fast ease-standard hover:border-accent/40 hover:bg-accent/[0.02] sm:px-5 sm:py-5', active && 'is-active')}>
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-x-5 gap-y-2">
        <div className="min-w-0">

          <m.div layoutId={`day-ordinal-${day.dayId}`} transition={{ duration: duration.page, ease: easing.decelerate }} className="inline-flex shrink-0 items-center">
            <DayOrdinalChip day={day.day}/>
          </m.div>
          {metadata.length > 0 && <p className="mt-1.5 break-words text-sm text-ink-secondary">{metadata.join(' · ')}</p>}
        </div>
        {day.weather && <DayWeather weather={day.weather}/>}
      </div>

      <h3 className="mt-4 break-words text-lg font-semibold leading-7 text-ink">{day.theme}</h3>

      {day.nodes.length > 0 && (<ol className="mt-4" aria-label={`第 ${day.day} 天核心安排`}>
          {day.nodes.map((node, index) => (<React.Fragment key={node.key}>
              <li className="grid min-w-0 grid-cols-[minmax(0,4.75rem)_minmax(0,1fr)] gap-x-3">
                {node.timeLabel
                    ? <time className="pt-0.5 text-xs font-semibold tabular-nums text-ink-secondary">{node.timeLabel}</time>
                    : <span aria-hidden/>}
                <div className="min-w-0 pb-3">

                  <div className="flex min-w-0 items-start gap-2">
                    <TimelineNodeMark node={node} ringed={false} className="mt-0.5"/>
                    <p className="min-w-0 break-words text-sm font-medium leading-5 text-ink">{node.title}</p>
                  </div>

                  {(node.durationLabel || node.priceLabel) && (<p className="mt-0.5 pl-6 text-xs text-ink-muted">
                      {[node.durationLabel, node.priceLabel].filter(Boolean).join(' · ')}
                    </p>)}
                </div>
              </li>
              {index < day.nodes.length - 1 && (<li aria-hidden className="grid grid-cols-[minmax(0,4.75rem)_minmax(0,1fr)] gap-x-3">
                  <span />

                  <span className="mb-2 ml-[7.5px] block h-3 w-px bg-stroke"/>
                </li>)}
            </React.Fragment>))}
        </ol>)}

      {day.hiddenNodeCount > 0 && <p className="mt-1 text-xs text-ink-muted">另有 {day.hiddenNodeCount} 项安排</p>}

      <span className="mt-4 flex items-center justify-between gap-1 border-t border-stroke/60 pt-3 text-xs font-semibold text-accent group-hover:text-[var(--color-accent-hover)]">
        查看详情
        <ArrowUpRight size={16} aria-hidden className="transition-transform duration-base ease-standard motion-safe:group-hover:translate-x-0.5 motion-safe:group-hover:-translate-y-0.5"/>
      </span>
    </button>);
};
