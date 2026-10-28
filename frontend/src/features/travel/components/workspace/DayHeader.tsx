import { type DayWeatherVM } from "../../model/itineraryPresentation";
import { DayOrdinalChip } from "./DayOrdinalChip";
import { DayWeatherBadge } from "./WeatherStrip";
export interface DayHeaderProps {
    dayId: string;
    day: number;
    dateLabel: string | null;
    weekdayLabel: string | null;
    destinationLabel: string | null;
    theme: string;
    weather: DayWeatherVM | null;
}
export function DayHeader({ dayId, day, dateLabel, weekdayLabel, destinationLabel, theme, weather, }: DayHeaderProps) {
    const tripMeta = [dateLabel, weekdayLabel, destinationLabel].filter((value): value is string => Boolean(value));
    return (<header data-testid={`day-header-${dayId}`} className="mb-5 min-w-0 overflow-hidden rounded-card border border-stroke bg-surface/55 px-4 py-3.5 sm:mb-6 sm:px-5">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-x-5 gap-y-2.5">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1">

            <div className="inline-flex shrink-0 items-center">
              <DayOrdinalChip day={day}/>
            </div>
            {tripMeta.length > 0 && (<p className="min-w-0 break-words text-xs text-ink-secondary">{tripMeta.join(' · ')}</p>)}
          </div>
          <h2 id={`delivery-day-${dayId}`} className="mt-1.5 break-words text-xl font-semibold tracking-[-0.015em] text-ink">
            {theme}
          </h2>
        </div>
        {weather && <DayWeatherBadge weather={weather}/>}
      </div>
    </header>);
}
