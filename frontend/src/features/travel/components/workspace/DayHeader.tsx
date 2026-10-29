import { type DayWeatherVM } from "../../model/itineraryPresentation";
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
    return (<header data-testid={`day-header-${dayId}`} className="journey-day-header">
      <div className="journey-day-header-meta">
        <strong className="journey-day-header-ordinal">第 {day} 天</strong>
        {tripMeta.length > 0 && <span className="journey-day-header-facts">{tripMeta.join(' · ')}</span>}
        {weather && <span className="journey-day-header-weather"><DayWeatherBadge weather={weather}/></span>}
      </div>
      <h2 id={`delivery-day-${dayId}`} className="journey-day-header-title">
        {theme}
      </h2>
    </header>);
}
